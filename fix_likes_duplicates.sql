-- SQL скрипт для очистки дубликатов в таблице likes и добавления unique constraint
-- Выполнить на production базе данных

BEGIN;

-- 1. Показываем текущие дубликаты
SELECT liker_id, liked_id, COUNT(*) as duplicates
FROM likes
GROUP BY liker_id, liked_id
HAVING COUNT(*) > 1;

-- 2. Удаляем дубликаты, оставляя только самый старый лайк для каждой пары
DELETE FROM likes
WHERE id NOT IN (
    SELECT MIN(id)
    FROM likes
    GROUP BY liker_id, liked_id
);

-- 3. Проверяем, что дубликатов больше нет
SELECT liker_id, liked_id, COUNT(*) as duplicates
FROM likes
GROUP BY liker_id, liked_id
HAVING COUNT(*) > 1;

-- 4. Добавляем unique constraint
ALTER TABLE likes
ADD CONSTRAINT unique_like_pair UNIQUE (liker_id, liked_id);

-- 5. Проверяем, что constraint создан
SELECT conname, contype
FROM pg_constraint
WHERE conrelid = 'likes'::regclass AND conname = 'unique_like_pair';

COMMIT;

-- Если что-то пошло не так, можно откатить:
-- ROLLBACK;
