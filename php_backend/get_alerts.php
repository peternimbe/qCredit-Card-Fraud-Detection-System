<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

$config = require __DIR__ . '/config.php';
$limit = isset($_GET['limit']) ? (int)$_GET['limit'] : 50;
$limit = max(1, min(500, $limit));
$statusFilter = isset($_GET['status']) ? $_GET['status'] : 'all';

$dsn = sprintf(
    'mysql:host=%s;port=%d;dbname=%s;charset=%s',
    $config['db']['host'],
    $config['db']['port'],
    $config['db']['dbname'],
    $config['db']['charset']
);

try {
    $pdo = new PDO($dsn, $config['db']['username'], $config['db']['password'], db_options($config['db']));

    $sql = "SELECT id, transaction_id, amount, merchant, transaction_time, raw_timestamp, transaction_type, description, risk_score, is_fraudulent, risk_level, model_scores, explanation FROM transactions ";
    $params = [];
    if ($statusFilter === 'Fraud') {
        $sql .= "WHERE is_fraudulent = 1 ";
    }
    $sql .= "ORDER BY id DESC LIMIT :limit";

    $stmt = $pdo->prepare($sql);
    $stmt->bindValue(':limit', $limit, PDO::PARAM_INT);
    $stmt->execute();

    $rows = $stmt->fetchAll();
    $out = [];
    foreach ($rows as $r) {
        $ts = null;
        if (!empty($r['raw_timestamp'])) {
            $raw = (int)$r['raw_timestamp'];
            if ($raw > 1000000000000) {
                $ts = $raw;
            } elseif ($raw > 1000000000) {
                $ts = $raw * 1000;
            } else {
                $ts = strtotime($r['transaction_time']) * 1000;
            }
        } else {
            $ts = strtotime($r['transaction_time']) * 1000;
        }

        $riskScore = isset($r['risk_score']) ? (int)$r['risk_score'] : 0;
        $status = (isset($r['is_fraudulent']) && (int)$r['is_fraudulent'] === 1) ? 'Fraud' : ($riskScore >= ($config['mail']['alert_threshold'] ?? 75) ? 'Fraud' : 'Safe');

        $modelScores = json_decode($r['model_scores'] ?? '{}', true);
        $explanation = json_decode($r['explanation'] ?? '{}', true);

        $out[] = [
            'id' => $r['transaction_id'] ?: ('dbid-' . $r['id']),
            'amount' => (float)$r['amount'],
            'merchant' => $r['merchant'] ?? '',
            'riskScore' => $riskScore,
            'status' => $status,
            'timestamp' => $ts,
            'type' => $r['transaction_type'] ?? '',
            'note' => $r['description'] ?? '',
            'riskLevel' => $r['risk_level'] ?? '',
            'modelScores' => is_array($modelScores) ? $modelScores : [],
            'explanation' => is_array($explanation) ? $explanation : [],
            'reason' => is_array($explanation) && !empty($explanation['reason']) ? $explanation['reason'] : ''
        ];
    }

    echo json_encode(['status' => 'ok', 'alerts' => $out]);
    exit;
} catch (PDOException $e) {
    http_response_code(500);
    echo json_encode(['error' => 'DB error', 'message' => $e->getMessage()]);
    exit;
}
