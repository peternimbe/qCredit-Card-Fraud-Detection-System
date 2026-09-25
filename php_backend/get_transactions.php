<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

$config = require __DIR__ . '/config.php';
$limit = isset($_GET['limit']) ? (int)$_GET['limit'] : 20;
$limit = max(1, min(200, $limit));

$dsn = sprintf(
    'mysql:host=%s;port=%d;dbname=%s;charset=%s',
    $config['db']['host'],
    $config['db']['port'],
    $config['db']['dbname'],
    $config['db']['charset']
);

try {
    $pdo = new PDO($dsn, $config['db']['username'], $config['db']['password'], db_options($config['db']));

    $sql = "SELECT id, transaction_id, amount, merchant, transaction_time, raw_timestamp, transaction_type, description, risk_score, is_fraudulent, risk_level, model_scores, explanation FROM transactions ORDER BY id DESC LIMIT :limit";
    $stmt = $pdo->prepare($sql);
    $stmt->bindValue(':limit', $limit, PDO::PARAM_INT);
    $stmt->execute();

    $rows = $stmt->fetchAll();
    $out = [];
    foreach ($rows as $r) {
        // Determine timestamp in ms
        $ts = null;
        if (!empty($r['raw_timestamp'])) {
            $raw = (int)$r['raw_timestamp'];
            if ($raw > 1000000000000) { // already ms
                $ts = $raw;
            } elseif ($raw > 1000000000) { // seconds
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

        $feature_snapshot = json_decode($r['feature_snapshot'] ?? '{}', true);
        $resolved_reason = '';
        if (is_array($explanation) && !empty($explanation['reason'])) {
            $resolved_reason = $explanation['reason'];
        } elseif (!empty($r['model_reason'])) {
            $resolved_reason = $r['model_reason'];
        }

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
            'feature_snapshot' => is_array($feature_snapshot) ? $feature_snapshot : [],
            'reason' => $resolved_reason
        ];
    }

    echo json_encode(['status' => 'ok', 'transactions' => $out]);
    exit;
} catch (PDOException $e) {
    http_response_code(500);
    echo json_encode(['error' => 'DB error', 'message' => $e->getMessage()]);
    exit;
}
