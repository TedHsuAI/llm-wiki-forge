# Android App 登入流程 — 程式碼層級搜尋記錄

## Session 背景

2026-06-24 查詢 "Android 登入流程"，LLM Wiki 回傳 `needs_semantic_expansion`，因為 Wiki 沒有 Android 登入的直接證據。

## 搜尋結果摘要

### 1. Android App 的識別方式

Android App 透過 HTTP Header 的 `Caller` 欄位標識自己：

- **檔案**：`TGDS.WebAPI/Helpers/CallerHelper.cs`
- **解析邏輯**：從 Header 讀取 `Caller` 欄位，解析為 `CallerType` 列舉
- **Android App 值**：`Android55688App`
- **iOS App 值**：`iOS55688App`

```csharp
// CallerHelper.cs 第 20-30 行
public static CallerType ParseCallerFromHeader(HttpRequestHeaders Headers)
{
    CallerType caller = CallerType.None;
    if (Headers.Contains("Caller"))
    {
        string strCaller = Headers.GetValues("Caller").First();
        Enum.TryParse<CallerType>(strCaller, out caller);
    }
    return caller;
}
```

### 2. 車機（IVE）登入流程（非 Android App）

- **API**：`TGDS.WebAPI/Controllers/mMSS/MemberController.cs` 第 344-419 行
- **路由**：`IveLoginReq`（HttpGet / HttpPost）
- **請求參數**：`MemSN`、`ssoToken`、`CarInfo`
- **回傳**：`loginToken`
- **資料庫**：寫入 `mIVE_SSOToken` 資料表

### 3. Android App 相關的 API 端點（Controllers/APP/）

| 模組 | 說明 |
|------|------|
| `APP/Mem/` | 會員相關（GetMemInfo、GetArrearsData、MemRefuse 等） |
| `APP/Dispatch/Order.cs` | 訂車流程 |
| `APP/Quotation/` | 報價相關 |
| `APP/Message/` | 訊息推播 |
| `APP/Query/` | 查詢（FinishJobs、MeterPrice、TakeCarRecords 等） |
| `APP/EstimatedFare/` | 預估車資 |

### 4. 未找到的部分

- 沒有找到 Android App 的「手機號碼 + 驗證碼」登入 API
- 沒有找到傳統的 MemberLogin / UserLogin 端點
- 可能透過外部 SSO 系統（如 molifeWebService 的 `ws_UserLogin`）處理

## 建議下一步

要完整了解 Android App 登入流程，需要確認：
1. Android App 的登入 API 在哪個專案？
2. 登入方式是什麼？（手機號碼 + OTP？SSO Token？）
3. 是否有外部認證系統？
