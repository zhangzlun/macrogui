# macrogui — 遊戲按鍵助手

黑金主題的遊戲重複按鍵工具（CustomTkinter GUI）。

## 架構

每個「角色」包含：

- **技能輪替**：F8 開始／暫停後常駐執行，各鍵獨立倒數、冷卻到了就按
- **組合**：任意數量，各自綁熱鍵；按熱鍵隨時插播（輪替暫停），打完 N 輪自動恢復輪替

## 安裝與執行

```bash
uv sync
uv run game_macro_gui.py
```

- macOS：第一次執行需在「系統設定 → 隱私權與安全性 → 輔助使用」授權終端機（pynput 監聽熱鍵用）
- Windows：`uv sync` 會自動加裝 pydirectinput（遊戲建議在全域設定勾選 DirectInput）

## 全域熱鍵

| 鍵 | 功能 |
|---|---|
| F8 | 開始／暫停技能輪替 |
| F9 | 結束程式 |
| 自訂 | 各組合的插播熱鍵（組合彈窗中設定） |

設定存於同目錄 `profiles.json`（已 gitignore，屬個人設定；舊版格式會自動升級）。
