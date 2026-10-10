-- 新增键值配置表（create_all 自动创建，无需手工执行）；Bark 推送配置存于 key='bark'
CREATE TABLE IF NOT EXISTS setting (key VARCHAR(64) PRIMARY KEY, value JSON);
