# 可直接交給 Pi 的操作指令

請套用隨附的 hk-quant-followup 修補包，再完成下列本機驗收與資料工作。
這不是上一份 33 檔修改包：本包基於你已提交的 e984171709846002bc6efdfb8cc13291f7c49e56。

## 一、先套用已完成的程式修復

1. 閱讀 docs/conflict-safety-followup.md、changes.patch、manifest.json。
2. 檢查 Git 狀態並保留未提交工作；備份本輪會用到的 data，包括 preparations、quality、reference、raw、processed。
3. 在壓縮檔解壓目錄先跑：
   python apply_changes.py --repo D:\hk-quant
   這一步只檢查。版本符合再加 --apply；它會另開分支及備份程式。
4. 若 HEAD 已更新，不得 reset 回舊版，請逐項合併；不要覆蓋你已修好的 SQLite close 與股票清單 180 秒時限。
5. 本包已修：零成交量不被直接刪除、無效成交量報錯、衝突持續記錄、舊報告匯入、離線與快取路徑不能忘記衝突，以及帶證據的 resolve-conflict 結案入口。不要重寫一套，也不要還原成「volume > 0 全刪」。

## 二、在 Windows 完成驗收

1. 安裝專案依賴，執行：
   python -m unittest tests.workflow.test_conflict_safety tests.workflow.test_workflow -v
   pytest tests/data/test_tencent_adapter.py -q
   pytest -m "not integration"
   pytest -m integration
   python -m compileall -q src tests examples
2. 原環境只跑過 47 個 workflow 測試、10 個 stdlib 測試，未跑完整 pytest／真實來源。請不要把這些數字說成新的真實資料驗收。
3. 確認 Pi extension 仍可載入與呼叫 workflow。先使用隔離資料目錄，不動正式資料。

## 三、處理只有本機才有的 44 筆衝突

1. 找出產生 44 筆衝突的 preparations 報告、來源回應與備份。把這些紀錄與資料一起複製到隔離目錄，不能只複製 processed，否則會丟掉問題歷史。
2. 執行 prepare/status，確認舊衝突會出現在 quality/unresolved_conflicts.json，重跑和 run --offline 仍然擋下。
3. 列出每筆股票、日期、欄位、兩邊的數字與來源；舊報告若沒數字，從 responses／備份還原。找不到就標記證據不足，不得猜。
4. 依同日、幣種、單位、復權口徑與收市狀態比對，分類為可解釋口徑差異／來源錯誤／仍無法判斷。不能預設某來源永遠正確。
5. 已查清楚的，保留證據並採用 docs/conflict-safety-followup.md 的 resolve-conflict 指令逐項結案。若須改市場數字，先備份、記錄來源及修正，再結案。這個指令只記錄決定，不會替你改價。
6. 不得靠刪 quality 或 preparations、填假證據、批次 verified=true、關閉檢查來解鎖。

## 四、修正交易日曆的真實資料

1. 記錄目前 exchange_calendars 的版本及日曆輸出，從 HKEX 官方歷史公告核對研究期間的特殊休市，尤其報告提到的 2023-09-01、2023-09-08。不要把這兩天當成全部例外。
2. 使用現有 calendar reference 匯入機制，建立有來源、日期範圍、核對紀錄的交易日曆；只在真正核實後標 verified。
3. 全市場休市、個股停牌、來源缺資料分開處理。零成交量本身不能證明休市或停牌。若 adapter 保留了非交易日佔位，保留 raw，依已核實日曆在研究輸入階段排除並記錄；確認它不會混入動量等指標的歷史窗口。
4. 個股零成交量保留且不能成交；缺失的停牌狀態不可直接當成價格缺口已解決。若還需改接線，補回歸測試並列出改動。

## 五、接通缺少的資料

1. 在這台 Windows 機器檢查 Eastmoney DNS、正常 HTTPS 連線與程式端點，區分本機網路問題、來源回應失敗、程式解析錯誤。不要關 TLS 驗證、硬塞未知 IP 或繞登入限制。
2. 用一檔股票的小區間先實測歷史換手率；核實分母口徑及百分比轉換，成功後再擴展到原七檔。若原來源仍不可用，查找並實測合適的替代來源；需要付費或帳戶才詢問我。
3. 財報同時核對報告期間、公布時間及修訂版本；沒有可信歷史可用時間，就不能作歷史財務回測。價格條件研究不應因此無故等待財務資料。
4. 公司行動逐項核對所選股票與研究區間的幣種、除淨日、付款日、拆股或分派等，取得證據後再補 coverage reference。資料不完整就維持阻擋，不得宣稱全部完整。

## 六、最後交付

1. 用真實資料完成一次價格／成交量示例：prepare → status → run → replay。策略只是驗證程式，不代表我的正式策略或投資優勢。
2. 換手率只有實際取得並核對後才跑；財務條件只有符合歷史時點要求後才跑。未取得的直接列 BLOCKED。
3. 修好本輪引起的回歸後，提交程式與文件到 PR #1 的原分支（若套用工具開了新分支，可把驗收後的 commit cherry-pick 到原 PR 分支），正常推送，不 force push、不直接合併 main。
4. 不提交 raw、processed、reference、preparations、quality、備份、實驗產物或金鑰。使用正常憑證管理，不把 token 放進 URL、命令或日誌；若認證失敗再告知。
5. 用大白話交代：程式改好了什麼、44 筆有多少已解決／未解決、真正增加了哪些資料、真實流程是否跑通、測試結果、commit 與 PR。不能用「接口已寫好」冒充「資料已取得」。

以上一般安裝、測試、免費公開資料核對與修復已授權，直接執行。只有付費、憑證或無法自行解決的重要資料衝突需要我介入。
