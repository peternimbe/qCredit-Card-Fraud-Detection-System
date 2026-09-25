<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

$config = require __DIR__ . '/config.php';

$dsn = sprintf(
    'mysql:host=%s;port=%d;dbname=%s;charset=%s',
    $config['db']['host'],
    $config['db']['port'],
    $config['db']['dbname'],
    $config['db']['charset']
);

try {
    $pdo = new PDO($dsn, $config['db']['username'], $config['db']['password'], db_options($config['db']));

    $stmt = $pdo->query('SELECT COUNT(*) AS c FROM information_schema.tables WHERE table_schema = ' . $pdo->quote($config['db']['dbname']) . ' AND table_name = ' . $pdo->quote('transactions'));
    $row = $stmt->fetch();
    $exists = ($row && isset($row['c']) && (int)$row['c'] > 0);

    $count = 0;
    if ($exists) {
        $r2 = $pdo->query('SELECT COUNT(*) AS c FROM transactions');
        $c2 = $r2->fetch();
        $count = (int)($c2['c'] ?? 0);
    }

    echo json_encode(['status' => 'ok', 'db' => $config['db']['dbname'], 'transactions_table_exists' => (bool)$exists, 'transactions_count' => $count]);
    exit;
} catch (PDOException $e) {
    http_response_code(500);
    echo json_encode(['error' => 'DB connection failed', 'message' => $e->getMessage()]);
    exit;
}
