"""
phase2.cli._terminal: コンソール出力ヘルパ (ANSIカラー + UTF-8出力).

Windows 10/11 のコンソールは os.system("") を一度実行することで
仮想ターミナル(VT)モードが有効化され、ANSIエスケープシーケンスが
そのまま色として表示されるようになる。
"""
from __future__ import annotations

import os
import sys


def _setup_console() -> None:
    """Windowsコンソールで ANSI / UTF-8 を有効化."""
    # UTF-8 で出力(日本語が化けないように)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    # Windows コンソールの VT モードを有効化(副作用利用)
    if os.name == "nt":
        os.system("")


_setup_console()


# ==============================================================
# ANSI エスケープ
# ==============================================================

_RESET   = "\x1b[0m"
_BOLD    = "\x1b[1m"
_RED     = "\x1b[31m"
_GREEN   = "\x1b[32m"
_YELLOW  = "\x1b[33m"
_BLUE    = "\x1b[34m"
_CYAN    = "\x1b[36m"
_GRAY    = "\x1b[90m"


# 色付け関数(--no-color オプション等で無効化可能にする余地を残す)
_use_color = True


def disable_color() -> None:
    global _use_color
    _use_color = False


def _wrap(code: str, s: str) -> str:
    if not _use_color:
        return s
    return f"{code}{s}{_RESET}"


def red(s: str) -> str:    return _wrap(_RED, s)
def green(s: str) -> str:  return _wrap(_GREEN, s)
def yellow(s: str) -> str: return _wrap(_YELLOW, s)
def blue(s: str) -> str:   return _wrap(_BLUE, s)
def cyan(s: str) -> str:   return _wrap(_CYAN, s)
def gray(s: str) -> str:   return _wrap(_GRAY, s)
def bold(s: str) -> str:   return _wrap(_BOLD, s)


def step(n: int, total: int, msg: str) -> str:
    """[1/8] 形式のステップ表示."""
    return f"[{cyan(f'{n}/{total}')}] {msg}"


def banner(title: str, width: int = 60, char: str = "=") -> str:
    """強調用バナー(上下に=線+中央タイトル)."""
    line = char * width
    return f"{line}\n {bold(title)}\n{line}"


def info(msg: str) -> None:
    print(f"     {msg}")


def warn(msg: str) -> None:
    print(f"     {yellow(msg)}")


def error(msg: str) -> None:
    print(f"     {red(msg)}")
