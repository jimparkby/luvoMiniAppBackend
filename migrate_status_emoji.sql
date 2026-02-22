-- Расширить колонку status для хранения emoji-строк
ALTER TABLE users ALTER COLUMN status TYPE VARCHAR(100);
