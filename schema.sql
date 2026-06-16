-- ==========================================
-- 蝦皮賣家百科智能助手 - 資料庫 Schema 定義檔
-- ==========================================

-- 1. 對話歷史紀錄表 (Chat Message History)
CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    message_type TEXT NOT NULL,       -- 'human' (使用者) 或 'ai' (AI 助手)
    content TEXT NOT NULL,            -- 訊息內文
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2. 賣家偏好與程序記憶表 (Seller Preferences & Profile)
CREATE TABLE IF NOT EXISTS user_profiles (
    user_namespace TEXT PRIMARY KEY,   -- 隔離標籤 (通常為 session_id，如 LINE user_id)
    profile_data TEXT NOT NULL         -- JSON 字串 (儲存賣家賣場類別、經驗等級、關注政策等)
);

-- 3. 賣家百科文章分段與向量索引表 (Segmented Nodes & Vector Embeddings)
CREATE TABLE IF NOT EXISTS segmented_nodes (
    node_id TEXT PRIMARY KEY,          -- LlamaIndex 節點唯一識別碼 (node_id)
    file_name TEXT NOT NULL,           -- 來源文章識別碼或檔名 (如 article_1234.html)
    text_content TEXT NOT NULL,        -- 分塊文字內容
    embedding_vector TEXT NOT NULL,    -- 向量值 (儲存 JSON 數值陣列, 如 [0.12, -0.45, ...])
    metadata_json TEXT NOT NULL,       -- 中介資料 (儲存 JSON 字串, 如標題、分類、子分類、網址)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
