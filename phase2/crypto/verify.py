"""
phase2.crypto.verify: 高レベル検証ラッパー + 署名者氏名抽出.

★Phase 3 / Step 1 (v2): JPKI OtherName 対応版
   実機検証 (docs/inspect_cert_san.py) で判明した構造:
     JPKI署名用cert の SubjectAltName は DirectoryName ではなく
     OtherName 形式で、JPKI独自OID (1.2.392.200149.8.5.5.x) を使用する。
     氏名(漢字) は OID 1.2.392.200149.8.5.5.1 の値として
     ASN.1 UTF8String でラップされて格納されている。

抽出順位:
   1) SAN 内 OtherName / JPKI 氏名OID (★最優先・実JPKI)
   2) SAN 内 DirectoryName / CN (将来の規格変更や他規格cert への保険)
   3) Subject DN / CN (フォールバック・JPKIでは識別符号)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence, TypedDict

from cryptography import x509 as c_x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import padding, rsa, ec
from cryptography.x509.oid import NameOID, ExtensionOID

from .p7s import (
    verify_p7s_against_data,
    extract_signer_cert_der,
    P7sVerificationError,
)


# ==============================================================
# JPKI 独自 SAN OtherName OIDs
#   出典: 公的個人認証サービス 署名用電子証明書 仕様
#         (地方公共団体情報システム機構 J-LIS)
# ==============================================================
JPKI_SAN_OID_KANJI_NAME = "1.2.392.200149.8.5.5.1"   # 氏名(漢字)
JPKI_SAN_OID_RESERVED   = "1.2.392.200149.8.5.5.2"   # 予備フィールド
JPKI_SAN_OID_GENDER     = "1.2.392.200149.8.5.5.3"   # 性別 (1=男, 2=女)
JPKI_SAN_OID_BIRTHDATE  = "1.2.392.200149.8.5.5.4"   # 生年月日 ([元号区分][YYYYMMDD])
JPKI_SAN_OID_KANJI_ADDR = "1.2.392.200149.8.5.5.5"   # 住所(漢字)
JPKI_SAN_OID_AUX_NUMBER = "1.2.392.200149.8.5.5.6"   # 補助番号 (17桁)


# ==============================================================
# 戻り値型
# ==============================================================

class VerifyResult(TypedDict, total=False):
    """verify_signed_image() の戻り値辞書."""
    valid: bool
    # 署名値と画像データの整合性 (有効期間/チェーン/失効とは独立)
    signature_valid: bool
    # 抽出した署名者氏名 (JPKI OtherName優先 → DirectoryName CN → Subject CN)
    signer_name: Optional[str]
    # 'san_jpki_other_name' / 'san_directory_name' / 'subject_cn' / 'unknown'
    signer_name_source: str
    # Subject CN(JPKI署名用cert では識別符号)。後方互換+情報目的
    signer_cn: Optional[str]
    # 証明書の有効期間 (ISO 8601)
    not_valid_before: Optional[str]
    not_valid_after: Optional[str]
    # 検証時刻が NotBefore <= now <= NotAfter の範囲内であるか
    validity_period_ok: bool
    # チェーン検証結果。trust_anchors 未指定時は None。
    chain_verified: Optional[bool]
    chain_error: Optional[str]
    # 失効確認結果: 'good' | 'revoked' | 'unknown' | 'not_checked'
    revocation_status: str
    revocation_detail: Optional[str]
    # 構造的エラー (検証以前の問題があった場合)
    error: Optional[str]


# ==============================================================
# OtherName.value (ASN.1ラップされたバイト列) を文字列にデコード
# ==============================================================

def _decode_other_name_value_as_string(raw_value: bytes) -> Optional[str]:
    """
    JPKI OtherName.value は ASN.1 UTF8String / PrintableString / IA5String
    のいずれかで符号化されている。複数の型を順に試し、どれかでパースできれば
    その文字列を返す。

    Args:
        raw_value: cryptography.x509.OtherName.value (DER-encoded TLV)

    Returns:
        デコード成功時は文字列、失敗時は None。
    """
    if not raw_value:
        return None

    # asn1crypto のオーバーヘッドを避けるため、まずタグ判別 + 直接デコード
    # (UTF8String=0x0c / PrintableString=0x13 / IA5String=0x16)
    try:
        tag = raw_value[0]
        if tag in (0x0C, 0x13, 0x16) and len(raw_value) >= 2:
            length_byte = raw_value[1]
            if length_byte < 0x80:
                # 短形式
                length = length_byte
                content = raw_value[2:2 + length]
                if len(content) == length:
                    if tag == 0x0C:
                        return content.decode("utf-8")
                    else:  # PrintableString / IA5String は ASCII
                        return content.decode("ascii", errors="replace")
            else:
                # 長形式: asn1crypto に任せる
                pass
    except Exception:
        pass

    # フォールバック: asn1crypto で正式パース
    try:
        from asn1crypto.core import UTF8String, PrintableString, IA5String
        for cls in (UTF8String, PrintableString, IA5String):
            try:
                return cls.load(raw_value).native
            except Exception:
                continue
    except ImportError:
        pass

    return None


# ==============================================================
# 署名者氏名抽出 (★JPKI実機構造に対応)
# ==============================================================

def extract_signer_name(cert: c_x509.Certificate) -> tuple[Optional[str], str]:
    """
    証明書から署名者氏名(漢字氏名)を抽出する。

    抽出順位:
      1) SAN内 OtherName (OID=JPKI_SAN_OID_KANJI_NAME)
         → 実機 JPKI署名用 cert はここに氏名が入る
      2) SAN内 DirectoryName の CommonName 属性
         → 他規格・将来規格への保険
      3) Subject DN の CommonName 属性
         → JPKI では『識別符号』(発行日時+乱数+連番)が入る

    Returns:
        (signer_name, source) のタプル。source は:
          - 'san_jpki_other_name' : JPKI仕様の OtherName 由来 (本来の正解)
          - 'san_directory_name'  : SAN内 DirectoryName.CN 由来
          - 'subject_cn'          : Subject CN フォールバック
          - 'unknown'             : 取得不能
    """
    # ---- 1) SAN 内 OtherName (JPKI規格) ----
    try:
        san_ext = cert.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        )
        san = san_ext.value

        # ★最優先: JPKI OtherName 氏名OID
        for gn in san:
            if isinstance(gn, c_x509.OtherName):
                if gn.type_id.dotted_string == JPKI_SAN_OID_KANJI_NAME:
                    decoded = _decode_other_name_value_as_string(gn.value)
                    if decoded:
                        return decoded, "san_jpki_other_name"

        # 次点: SAN内 DirectoryName の CN
        for gn in san:
            if isinstance(gn, c_x509.DirectoryName):
                cn_attrs = gn.value.get_attributes_for_oid(NameOID.COMMON_NAME)
                if cn_attrs:
                    val = cn_attrs[0].value
                    if val:
                        return val, "san_directory_name"
    except c_x509.ExtensionNotFound:
        pass
    except Exception:
        pass

    # ---- 2) Subject CN フォールバック ----
    try:
        cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if cn_attrs:
            val = cn_attrs[0].value
            if val:
                return val, "subject_cn"
    except Exception:
        pass

    return None, "unknown"


def _safe_subject_cn(cert: c_x509.Certificate) -> Optional[str]:
    """Subject CN を取得(取れなければ None)."""
    try:
        cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if cn_attrs:
            return cn_attrs[0].value
    except Exception:
        pass
    return None


def _safe_validity(cert: c_x509.Certificate) -> tuple[Optional[str], Optional[str]]:
    """有効期間 (Not Before / Not After) をISO形式で返す."""
    try:
        return (
            cert.not_valid_before_utc.isoformat(),
            cert.not_valid_after_utc.isoformat(),
        )
    except AttributeError:
        try:
            return (
                cert.not_valid_before.isoformat(),
                cert.not_valid_after.isoformat(),
            )
        except Exception:
            return None, None


def _cert_validity_window(cert: c_x509.Certificate) -> tuple[Optional[datetime], Optional[datetime]]:
    """有効期間を aware datetime (UTC) で返す."""
    try:
        return cert.not_valid_before_utc, cert.not_valid_after_utc
    except AttributeError:
        try:
            nvb = cert.not_valid_before
            nva = cert.not_valid_after
            if nvb.tzinfo is None:
                nvb = nvb.replace(tzinfo=timezone.utc)
            if nva.tzinfo is None:
                nva = nva.replace(tzinfo=timezone.utc)
            return nvb, nva
        except Exception:
            return None, None


def _is_within_validity_period(cert: c_x509.Certificate, now: Optional[datetime] = None) -> bool:
    """NotBefore <= now <= NotAfter であるか。取得できない場合は False を返す。"""
    nvb, nva = _cert_validity_window(cert)
    if nvb is None or nva is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    return nvb <= now <= nva


def _verify_cert_signed_by(child: c_x509.Certificate, issuer: c_x509.Certificate) -> bool:
    """child の署名が issuer の公開鍵で検証できるか。"""
    try:
        if child.issuer != issuer.subject:
            return False
        pub = issuer.public_key()
        sig = child.signature
        tbs = child.tbs_certificate_bytes
        algo = child.signature_hash_algorithm
        if isinstance(pub, rsa.RSAPublicKey):
            pub.verify(sig, tbs, padding.PKCS1v15(), algo)
        elif isinstance(pub, ec.EllipticCurvePublicKey):
            pub.verify(sig, tbs, ec.ECDSA(algo))
        else:
            return False
        return True
    except InvalidSignature:
        return False
    except Exception:
        return False


def _verify_chain(
    leaf: c_x509.Certificate,
    intermediates: Sequence[c_x509.Certificate],
    trust_anchors: Sequence[c_x509.Certificate],
    now: Optional[datetime] = None,
) -> tuple[bool, Optional[str]]:
    """leaf -> intermediates -> trust_anchors のチェーンを検証する。

    検証内容:
      - 各段で issuer.subject == child.issuer
      - 各段で署名が親の公開鍵で検証できる
      - 各証明書の有効期間に検証時刻が含まれる
      - チェーンが trust_anchor のいずれかに到達する

    フルPKIX (名前制約・ポリシー・拡張) は実施しない。最低限の信頼経路確認。
    """
    if not trust_anchors:
        return False, "trust_anchors が空です"
    if now is None:
        now = datetime.now(timezone.utc)

    # 全証明書の有効期間を確認
    for cert in [leaf, *intermediates]:
        if not _is_within_validity_period(cert, now):
            return False, f"証明書の有効期間外: {_safe_subject_cn(cert) or '(CN不明)'}"

    current = leaf
    visited = set()  # ループ防止用
    pool = list(intermediates) + list(trust_anchors)
    max_depth = 10
    for _ in range(max_depth):
        fp = current.fingerprint(current.signature_hash_algorithm)
        if fp in visited:
            return False, "チェーンに循環があります"
        visited.add(fp)

        # current が trust_anchor 自身であれば成功
        for ta in trust_anchors:
            if current.subject == ta.subject and current.fingerprint(current.signature_hash_algorithm) == ta.fingerprint(ta.signature_hash_algorithm):
                return True, None

        # current の issuer を探す
        issuer = None
        for candidate in pool:
            if candidate.subject == current.issuer and _verify_cert_signed_by(current, candidate):
                # trust_anchor に到達した場合、その時点で有効期間も確認
                if candidate in trust_anchors and not _is_within_validity_period(candidate, now):
                    return False, f"信頼アンカーの有効期間外: {_safe_subject_cn(candidate) or '(CN不明)'}"
                issuer = candidate
                break

        if issuer is None:
            return False, f"発行元証明書が見つかりません: issuer={current.issuer.rfc4514_string()}"

        # trust_anchor に到達したか
        if issuer in trust_anchors:
            return True, None
        current = issuer

    return False, "チェーン深度上限に達しました"


def _check_revocation(
    cert: c_x509.Certificate,
    crls: Sequence[c_x509.CertificateRevocationList],
    issuer: Optional[c_x509.Certificate] = None,
) -> tuple[str, Optional[str]]:
    """CRL に基づき失効状態を返す。

    Returns:
        ('good' | 'revoked' | 'unknown', detail) のタプル。
        - 'good'    : シリアル番号がいずれのCRLにも含まれていない
        - 'revoked' : 該当シリアル番号がCRLで失効登録されている
        - 'unknown' : 一致するCRLが見つからない / 検証不能
    """
    if not crls:
        return "unknown", "CRLが指定されていません"

    serial = cert.serial_number
    matched_any_issuer = False
    for crl in crls:
        # CRL の発行者が cert の issuer と一致するもののみ評価
        if crl.issuer != cert.issuer:
            continue
        matched_any_issuer = True
        # issuer が分かれば CRL の署名検証も実施
        if issuer is not None:
            try:
                if not crl.is_signature_valid(issuer.public_key()):
                    return "unknown", "CRL署名が不正です"
            except Exception as e:
                return "unknown", f"CRL署名検証に失敗: {type(e).__name__}"
        revoked = crl.get_revoked_certificate_by_serial_number(serial)
        if revoked is not None:
            return "revoked", f"serial={serial:x} がCRLで失効登録されています"

    if not matched_any_issuer:
        return "unknown", "対象証明書の発行者と一致するCRLがありません"
    return "good", None


def _load_certs(cert_blobs: Optional[Sequence[bytes]]) -> list[c_x509.Certificate]:
    """DER / PEM の両方を許容して証明書を読み込む。"""
    result: list[c_x509.Certificate] = []
    if not cert_blobs:
        return result
    for blob in cert_blobs:
        try:
            result.append(c_x509.load_der_x509_certificate(blob))
            continue
        except Exception:
            pass
        try:
            result.append(c_x509.load_pem_x509_certificate(blob))
        except Exception:
            pass
    return result


def _load_crls(crl_blobs: Optional[Sequence[bytes]]) -> list[c_x509.CertificateRevocationList]:
    """DER / PEM の両方を許容してCRLを読み込む。"""
    result: list[c_x509.CertificateRevocationList] = []
    if not crl_blobs:
        return result
    for blob in crl_blobs:
        try:
            result.append(c_x509.load_der_x509_crl(blob))
            continue
        except Exception:
            pass
        try:
            result.append(c_x509.load_pem_x509_crl(blob))
        except Exception:
            pass
    return result


# ==============================================================
# 高レベル検証ラッパー
# ==============================================================

def verify_signed_image(
    image_bytes: bytes,
    p7s_bytes: bytes,
    *,
    trust_anchors: Optional[Sequence[bytes]] = None,
    intermediate_certs: Optional[Sequence[bytes]] = None,
    crls: Optional[Sequence[bytes]] = None,
    check_validity_period: bool = True,
    now: Optional[datetime] = None,
) -> VerifyResult:
    """
    画像と分離署名(p7s)を検証して結果を辞書で返す。

    Args:
        image_bytes: 検証対象の画像バイト列
        p7s_bytes:   分離署名 (CMS/PKCS#7) バイト列
        trust_anchors: JPKI 署名用CAなどのルート/中間CA証明書 (DER または PEM)。
                       省略時はチェーン検証を行わない (chain_verified=None)。
        intermediate_certs: 任意の中間CA証明書群 (DER または PEM)
        crls: CRL バイト列 (DER または PEM)。省略時は失効確認を行わない。
        check_validity_period: True の場合、署名者証明書の有効期間を valid に反映する。
        now: 検証時刻 (UTC aware datetime)。テスト用途で固定可能。

    Returns:
        VerifyResult dict (主要キー):
          - valid:                bool  (署名 + 有効期間 + (任意)チェーン + (任意)失効)
          - signature_valid:      bool  (署名値と画像の整合性のみ)
          - signer_name / signer_name_source / signer_cn
          - not_valid_before/after / validity_period_ok
          - chain_verified:       Optional[bool]
          - chain_error:          Optional[str]
          - revocation_status:    'good' | 'revoked' | 'unknown' | 'not_checked'
          - revocation_detail:    Optional[str]
          - error:                Optional[str]
    """
    result: VerifyResult = {
        "valid": False,
        "signature_valid": False,
        "signer_name": None,
        "signer_name_source": "unknown",
        "signer_cn": None,
        "not_valid_before": None,
        "not_valid_after": None,
        "validity_period_ok": False,
        "chain_verified": None,
        "chain_error": None,
        "revocation_status": "not_checked",
        "revocation_detail": None,
        "error": None,
    }

    try:
        sig_ok = verify_p7s_against_data(p7s_bytes, image_bytes)
        result["signature_valid"] = sig_ok

        cert_der = extract_signer_cert_der(p7s_bytes)
        cert = c_x509.load_der_x509_certificate(cert_der)

        name, source = extract_signer_name(cert)
        result["signer_name"] = name
        result["signer_name_source"] = source

        result["signer_cn"] = _safe_subject_cn(cert)

        nvb, nva = _safe_validity(cert)
        result["not_valid_before"] = nvb
        result["not_valid_after"] = nva

        # 有効期間チェック
        validity_ok = _is_within_validity_period(cert, now)
        result["validity_period_ok"] = validity_ok

        # チェーン検証 (trust_anchors が指定された場合のみ)
        trust_certs = _load_certs(trust_anchors)
        intermediate_objs = _load_certs(intermediate_certs)
        chain_ok: Optional[bool] = None
        if trust_certs:
            chain_ok, chain_err = _verify_chain(cert, intermediate_objs, trust_certs, now)
            result["chain_verified"] = chain_ok
            result["chain_error"] = chain_err

        # 失効確認 (CRL が指定された場合のみ)
        crl_objs = _load_crls(crls)
        if crl_objs:
            # CRL の署名検証用に、cert の発行元証明書を中間+信頼アンカーから探索
            issuer_cert = None
            for c in list(intermediate_objs) + list(trust_certs):
                if c.subject == cert.issuer:
                    issuer_cert = c
                    break
            rev_status, rev_detail = _check_revocation(cert, crl_objs, issuer_cert)
            result["revocation_status"] = rev_status
            result["revocation_detail"] = rev_detail

        # 総合 valid 判定
        overall = sig_ok
        if check_validity_period:
            overall = overall and validity_ok
        if chain_ok is not None:
            overall = overall and chain_ok
        if result["revocation_status"] == "revoked":
            overall = False
        result["valid"] = overall

    except P7sVerificationError as e:
        result["error"] = f"P7sVerificationError: {e}"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    return result
