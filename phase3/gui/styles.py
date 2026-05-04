"""
phase3.gui.styles: モダンフラットデザインの QSS (Qt Style Sheet).

カラーパレット(Tailwind系の中間色を採用):
  - 背景:        #F5F7FA (薄いグレー)
  - サーフェス:  #FFFFFF (白)
  - 境界線:      #E1E5EB
  - 主テキスト:  #1F2937
  - 副テキスト:  #6B7280
  - アクセント青(primary):  #3B82F6 / hover #2563EB / pressed #1D4ED8
  - 成功緑:      #10B981
  - 警告黄:      #F59E0B
  - エラー赤:    #EF4444
  - D&Dハイライト: 背景 #DBEAFE / 枠 #3B82F6
"""
from __future__ import annotations


# ====== カラー定数 (他モジュールから参照可) ======
COLOR_BG               = "#F5F7FA"
COLOR_SURFACE          = "#FFFFFF"
COLOR_BORDER           = "#E1E5EB"
COLOR_TEXT_PRIMARY     = "#1F2937"
COLOR_TEXT_SECONDARY   = "#6B7280"
COLOR_PRIMARY          = "#3B82F6"
COLOR_PRIMARY_HOVER    = "#2563EB"
COLOR_PRIMARY_PRESSED  = "#1D4ED8"
COLOR_SUCCESS          = "#10B981"
COLOR_WARNING          = "#F59E0B"
COLOR_ERROR            = "#EF4444"
COLOR_DRAGGING_BG      = "#DBEAFE"
COLOR_DRAGGING_BORDER  = "#3B82F6"


APP_STYLESHEET = f"""
/* ====== Global ====== */
QWidget {{
    font-family: "Segoe UI", "Yu Gothic UI", "Meiryo", sans-serif;
    color: {COLOR_TEXT_PRIMARY};
}}

QMainWindow {{
    background-color: {COLOR_BG};
}}

/* ====== Dialog (PinDialog 含む) — システムダークモード対策 ====== */
/* Windows 11 ダークモード環境でも常にライトテーマで描画する */
QDialog {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT_PRIMARY};
}}
QDialog QLabel {{
    color: {COLOR_TEXT_PRIMARY};
    background-color: transparent;
}}
QDialog QLineEdit {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT_PRIMARY};
    selection-background-color: {COLOR_PRIMARY};
    selection-color: white;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 6px 10px;
}}
QDialog QLineEdit:focus {{
    border: 2px solid {COLOR_PRIMARY};
    padding: 5px 9px;
}}

/* ====== 中央スタック (D&D 視覚フィードバック対象) ====== */
QStackedWidget#centralStack {{
    background-color: {COLOR_BG};
    border: 2px dashed transparent;
    border-radius: 12px;
    margin: 16px;
}}
QStackedWidget#centralStack[dragging="true"] {{
    background-color: {COLOR_DRAGGING_BG};
    border: 2px dashed {COLOR_DRAGGING_BORDER};
}}

/* ====== Welcome Panel ====== */
QWidget#welcomePanel {{
    background-color: transparent;
}}
QLabel#welcomeTitle {{
    font-size: 32pt;
    font-weight: bold;
    color: {COLOR_TEXT_PRIMARY};
    padding: 12px;
}}
QLabel#welcomeIcon {{
    font-size: 64pt;
    padding: 16px;
}}
QLabel#welcomeSubtitle {{
    font-size: 14pt;
    color: {COLOR_TEXT_SECONDARY};
    padding: 8px;
}}
QLabel#welcomeHint {{
    font-size: 11pt;
    color: {COLOR_TEXT_SECONDARY};
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 16px 24px;
    margin: 16px;
}}

/* ====== Sign / Verify Panel 共通 ====== */
QLabel#panelTitle {{
    font-size: 22pt;
    font-weight: bold;
    color: {COLOR_TEXT_PRIMARY};
    padding: 8px;
}}
QLabel#fileLabel {{
    font-size: 11pt;
    color: {COLOR_TEXT_PRIMARY};
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 16px;
}}
QLabel#statusLabel {{
    font-size: 11pt;
    color: {COLOR_TEXT_SECONDARY};
    padding: 8px;
}}
QLabel#successLabel {{
    font-size: 14pt;
    font-weight: bold;
    color: {COLOR_SUCCESS};
    padding: 8px;
}}
QLabel#errorLabel {{
    font-size: 14pt;
    font-weight: bold;
    color: {COLOR_ERROR};
    padding: 8px;
}}

/* ====== Buttons ====== */
QPushButton#primaryButton {{
    background-color: {COLOR_PRIMARY};
    color: white;
    font-size: 13pt;
    font-weight: bold;
    border: none;
    border-radius: 8px;
    padding: 12px 24px;
    min-height: 24px;
}}
QPushButton#primaryButton:hover {{
    background-color: {COLOR_PRIMARY_HOVER};
}}
QPushButton#primaryButton:pressed {{
    background-color: {COLOR_PRIMARY_PRESSED};
}}
QPushButton#primaryButton:disabled {{
    background-color: {COLOR_BORDER};
    color: {COLOR_TEXT_SECONDARY};
}}

QPushButton#backButton {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 10pt;
}}
QPushButton#backButton:hover {{
    background-color: {COLOR_BG};
    border-color: {COLOR_PRIMARY};
    color: {COLOR_PRIMARY};
}}

/* ====== Progress Bar ====== */
QProgressBar#progressBar {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    height: 8px;
    text-align: center;
}}
QProgressBar#progressBar::chunk {{
    background-color: {COLOR_PRIMARY};
    border-radius: 4px;
}}

/* ====== StatusBar ====== */
QStatusBar {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT_SECONDARY};
    border-top: 1px solid {COLOR_BORDER};
    padding: 4px 8px;
    font-size: 10pt;
}}

/* ====== ScrollArea (中央コンテンツ用) ====== */
QScrollArea#verifyScroll {{
    background-color: transparent;
    border: none;
}}
QWidget#verifyScrollInner {{
    background-color: transparent;
}}

/* ====== 検証結果カード(成功/改ざん/警告) ====== */
QFrame#successCard {{
    background-color: #ECFDF5;       /* 薄い緑(emerald-50) */
    border: 2px solid {COLOR_SUCCESS};
    border-radius: 12px;
    padding: 0px;
}}
QFrame#errorCard {{
    background-color: #FEF2F2;       /* 薄い赤(red-50) */
    border: 2px solid {COLOR_ERROR};
    border-radius: 12px;
    padding: 0px;
}}
QFrame#warningCard {{
    background-color: #FFFBEB;       /* 薄い黄(amber-50) */
    border: 2px solid {COLOR_WARNING};
    border-radius: 12px;
    padding: 0px;
}}

QLabel#cardTitleSuccess {{
    font-size: 18pt;
    font-weight: bold;
    color: {COLOR_SUCCESS};
    padding: 4px;
}}
QLabel#cardTitleError {{
    font-size: 18pt;
    font-weight: bold;
    color: {COLOR_ERROR};
    padding: 4px;
}}
QLabel#cardTitleWarning {{
    font-size: 18pt;
    font-weight: bold;
    color: {COLOR_WARNING};
    padding: 4px;
}}

QLabel#cardBody {{
    font-size: 11pt;
    color: {COLOR_TEXT_PRIMARY};
    padding: 6px;
    background-color: transparent;
    border: none;
}}

QLabel#cardSubtle {{
    font-size: 10pt;
    color: {COLOR_TEXT_SECONDARY};
    padding: 4px;
    background-color: transparent;
    border: none;
}}
"""
