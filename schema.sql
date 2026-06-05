-- ==========================================
-- GCP 智能財報分析助手 - 資料庫 Schema 定義檔
-- ==========================================

-- 1. 對話歷史紀錄表 (Chat Message History)
CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    message_type TEXT NOT NULL,       -- 'human' (使用者) 或 'ai' (AI 助手)
    content TEXT NOT NULL,            -- 訊息內文
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2. 使用者偏好與程序記憶表 (User Preferences & Profile)
CREATE TABLE IF NOT EXISTS user_profiles (
    user_namespace TEXT PRIMARY KEY,   -- 隔離標籤 (通常為 session_id)
    profile_data TEXT NOT NULL         -- JSON 字串 (儲存投資偏好、風險度、關注指標等)
);

-- 3. 財報分段與向量索引表 (Segmented Nodes & Vector Embeddings)
CREATE TABLE IF NOT EXISTS segmented_nodes (
    node_id TEXT PRIMARY KEY,          -- LlamaIndex 節點唯一識別碼 (node_id)
    file_name TEXT NOT NULL,           -- 來源財報檔名 (如 TSMC_2026Q1.pdf)
    text_content TEXT NOT NULL,        -- 分塊文字內容
    embedding_vector TEXT NOT NULL,    -- 向量值 (儲存 JSON 數值陣列, 如 [0.12, -0.45, ...])
    metadata_json TEXT NOT NULL,       -- 中介資料 (儲存 JSON 字串, 如頁碼、會計年度、季度、重要指標)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
