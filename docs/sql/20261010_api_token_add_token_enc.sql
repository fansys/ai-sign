-- api_token 增加 token_enc：加密保存 API Token 原文，供面板显示带星号的形式并支持复制。
-- 旧 token 该列为 NULL（只有哈希，原文不可恢复）。服务启动时 init_db() 会自动执行等价迁移。
ALTER TABLE api_token ADD COLUMN token_enc BLOB;
