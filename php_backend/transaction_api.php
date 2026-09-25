<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, Authorization');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(204);
    exit;
}

$config = require __DIR__ . '/config.php';

$input = json_decode(file_get_contents('php://input'), true);
if (json_last_error() !== JSON_ERROR_NONE) {
    http_response_code(400);
    echo json_encode(['error' => 'Invalid JSON payload']);
    exit;
}

$userEmail = filter_var($input['user_email'] ?? '', FILTER_VALIDATE_EMAIL);
if (!$userEmail) {
    $userEmail = filter_var($input['email'] ?? '', FILTER_VALIDATE_EMAIL);
}
$required = ['transaction_type', 'amount', 'timestamp'];
foreach ($required as $field) {
    if (!isset($input[$field])) {
        http_response_code(400);
        echo json_encode(['error' => "Missing required field: $field"]);
        exit;
    }
}

$timestampMilliseconds = (int)$input['timestamp'];
$timestampSeconds = $timestampMilliseconds > 1000000000000
    ? (int)floor($timestampMilliseconds / 1000)
    : $timestampMilliseconds;

// Normalize dataset fields and fallback values
$feature_snapshot_raw = null;
if (isset($input['feature_snapshot'])) {
    $feature_snapshot_raw = $input['feature_snapshot'];
} else {
    // prefer the scored fields if provided, otherwise store the whole input
    $feature_snapshot_raw = $input;
}

$transaction = [
    'transaction_id' => $input['transaction_id'] ?? uniqid('tx_', true),
    'transaction_type' => $input['transaction_type'],
    'amount' => (float)$input['amount'],
    'oldbalanceOrg' => isset($input['oldbalanceOrg']) ? (float)$input['oldbalanceOrg'] : null,
    'newbalanceOrig' => isset($input['newbalanceOrig']) ? (float)$input['newbalanceOrig'] : null,
    'oldbalanceDest' => isset($input['oldbalanceDest']) ? (float)$input['oldbalanceDest'] : null,
    'newbalanceDest' => isset($input['newbalanceDest']) ? (float)$input['newbalanceDest'] : null,
    'timestamp' => (int)$input['timestamp'],
    'device_time_ms' => isset($input['device_time_ms']) ? (int)$input['device_time_ms'] : (int)$input['timestamp'],
    'device_timezone' => $input['device_timezone'] ?? null,
    'device_timezone_offset_minutes' => isset($input['device_timezone_offset_minutes']) ? (int)$input['device_timezone_offset_minutes'] : null,
    'server_received_timestamp' => (int)round(microtime(true) * 1000),
    'transaction_time' => date('Y-m-d H:i:s', $timestampSeconds),
    'description' => $input['description'] ?? '',
    'recipient' => $input['recipient'] ?? '',
    'merchant' => $input['merchant'] ?? '',
    'time_hour' => isset($input['time_hour']) ? (int)$input['time_hour'] : null,
    'merchant_risk' => isset($input['merchant_risk']) ? (float)$input['merchant_risk'] : null,
    'merchant_category' => isset($input['merchant_cat']) ? $input['merchant_cat'] : (isset($input['merchant_category']) ? $input['merchant_category'] : null),
    'country' => isset($input['country']) ? strtoupper((string)$input['country']) : null,
    'location_latitude' => isset($input['location_latitude']) ? (float)$input['location_latitude'] : null,
    'location_longitude' => isset($input['location_longitude']) ? (float)$input['location_longitude'] : null,
    'location_accuracy_m' => isset($input['location_accuracy_m']) ? (float)$input['location_accuracy_m'] : null,
    'location_timestamp' => isset($input['location_timestamp']) ? (int)$input['location_timestamp'] : null,
    'location_source' => $input['location_source'] ?? 'unavailable',
    'time_feature' => isset($input['Time']) ? (float)$input['Time'] : (float)$input['timestamp'],
    'feature_snapshot' => json_encode($feature_snapshot_raw),
];
$transaction['clock_skew_seconds'] = round(($transaction['server_received_timestamp'] - $transaction['device_time_ms']) / 1000, 3);
if (is_array($feature_snapshot_raw)) {
    $feature_snapshot_raw['server_received_timestamp'] = $transaction['server_received_timestamp'];
    $feature_snapshot_raw['clock_skew_seconds'] = $transaction['clock_skew_seconds'];
    $transaction['feature_snapshot'] = json_encode($feature_snapshot_raw);
}

// Accept V1..V28 if provided, otherwise default to 0.0
for ($i = 1; $i <= 28; $i++) {
    $key = "V$i";
    $transaction[$key] = isset($input[$key]) ? (float)$input[$key] : 0.0;
}

$prediction = [
    'risk_score' => isset($input['risk_score']) ? (int)$input['risk_score'] : (isset($input['fraud_probability']) ? (int)round((float)$input['fraud_probability'] * 100) : null),
    'is_fraudulent' => isset($input['is_fraudulent']) ? (int)$input['is_fraudulent'] : (isset($input['fraud_probability']) && (float)$input['fraud_probability'] > 0.5 ? 1 : 0),
    'risk_level' => $input['risk_level'] ?? '',
    'model_scores' => isset($input['model_scores']) ? $input['model_scores'] : [],
    'explanation' => isset($input['explanation']) ? $input['explanation'] : [],
    'model_reason' => isset($input['explanation']['reason']) ? $input['explanation']['reason'] : '',
];

$saveResult = saveTransactionToDatabase($config['db'], $transaction, $prediction);
if (is_array($saveResult) && isset($saveResult['error']) && $saveResult['error'] === true) {
    http_response_code(500);
    echo json_encode(['error' => 'Failed to save transaction to database', 'db_error' => $saveResult['message']]);
    exit;
}
if ($saveResult === false) {
    http_response_code(500);
    echo json_encode(['error' => 'Failed to save transaction to database']);
    exit;
}

$emailStatus = null;
if ($userEmail) {
    $emailStatus = sendTransactionNotification($config['mail'] ?? [], $userEmail, $transaction, $prediction);
}

$response = [
    'status' => 'success',
    'transaction_id' => $transaction['transaction_id'],
    'prediction' => $prediction,
    'database_id' => $saveResult,
    'email_status' => $emailStatus,
];

echo json_encode($response);

function saveTransactionToDatabase(array $dbConfig, array $transaction, array $prediction)
{
    $dsn = sprintf(
        'mysql:host=%s;port=%d;dbname=%s;charset=%s',
        $dbConfig['host'],
        $dbConfig['port'],
        $dbConfig['dbname'],
        $dbConfig['charset']
    );

    try {
        $pdo = new PDO($dsn, $dbConfig['username'], $dbConfig['password'], db_options($dbConfig));

        $sql = "INSERT INTO transactions (
            transaction_id,
            transaction_type,
            description,
            recipient,
            merchant,
            amount,
            oldbalanceOrg,
            newbalanceOrig,
            oldbalanceDest,
            newbalanceDest,
            time_hour,
            merchant_risk,
            merchant_category,
            country,
            location_latitude,
            location_longitude,
            location_accuracy_m,
            location_source,
            device_time_ms,
            device_timezone,
            device_timezone_offset_minutes,
            server_received_timestamp,
            clock_skew_seconds,
            transaction_time,
            raw_timestamp,
            Time,
            risk_score,
            is_fraudulent,
            risk_level,
            model_scores,
            explanation,
            feature_snapshot,
            model_reason,
            created_at,
            updated_at
        ) VALUES (
            :transaction_id,
            :transaction_type,
            :description,
            :recipient,
            :merchant,
            :amount,
            :oldbalanceOrg,
            :newbalanceOrig,
            :oldbalanceDest,
            :newbalanceDest,
            :time_hour,
            :merchant_risk,
            :merchant_category,
            :country,
            :location_latitude,
            :location_longitude,
            :location_accuracy_m,
            :location_source,
            :device_time_ms,
            :device_timezone,
            :device_timezone_offset_minutes,
            :server_received_timestamp,
            :clock_skew_seconds,
            :transaction_time,
            :raw_timestamp,
            :Time,
            :risk_score,
            :is_fraudulent,
            :risk_level,
            :model_scores,
            :explanation,
            :feature_snapshot,
            :model_reason,
            NOW(),
            NOW()
        )";

        $stmt = $pdo->prepare($sql);
        $stmt->execute([
            ':transaction_id' => $transaction['transaction_id'],
            ':transaction_type' => $transaction['transaction_type'],
            ':description' => $transaction['description'],
            ':recipient' => $transaction['recipient'],
            ':merchant' => $transaction['merchant'],
            ':amount' => $transaction['amount'],
            ':oldbalanceOrg' => $transaction['oldbalanceOrg'],
            ':newbalanceOrig' => $transaction['newbalanceOrig'],
            ':oldbalanceDest' => $transaction['oldbalanceDest'],
            ':newbalanceDest' => $transaction['newbalanceDest'],
            ':time_hour' => $transaction['time_hour'],
            ':merchant_risk' => $transaction['merchant_risk'],
            ':merchant_category' => $transaction['merchant_category'],
            ':country' => $transaction['country'],
            ':location_latitude' => $transaction['location_latitude'],
            ':location_longitude' => $transaction['location_longitude'],
            ':location_accuracy_m' => $transaction['location_accuracy_m'],
            ':location_source' => $transaction['location_source'],
            ':device_time_ms' => $transaction['device_time_ms'],
            ':device_timezone' => $transaction['device_timezone'],
            ':device_timezone_offset_minutes' => $transaction['device_timezone_offset_minutes'],
            ':server_received_timestamp' => $transaction['server_received_timestamp'],
            ':clock_skew_seconds' => $transaction['clock_skew_seconds'],
            ':transaction_time' => $transaction['transaction_time'],
            ':raw_timestamp' => $transaction['timestamp'],
            ':Time' => $transaction['time_feature'],
            ':risk_score' => $prediction['risk_score'] ?? null,
            ':is_fraudulent' => $prediction['is_fraudulent'] ?? 0,
            ':risk_level' => $prediction['risk_level'] ?? '',
            ':model_scores' => is_array($prediction['model_scores']) ? json_encode($prediction['model_scores']) : ($prediction['model_scores'] ?? null),
            ':explanation' => is_array($prediction['explanation']) ? json_encode($prediction['explanation']) : ($prediction['explanation'] ?? null),
            ':feature_snapshot' => $transaction['feature_snapshot'],
            ':model_reason' => $prediction['model_reason'] ?? '',
        ]);

        return (int)$pdo->lastInsertId();
    } catch (PDOException $e) {
        $msg = 'Database save error: ' . $e->getMessage();
        error_log($msg);
        return ['error' => true, 'message' => $e->getMessage()];
    }
}

function sendTransactionNotification(array $mailConfig, string $to, array $transaction, array $prediction)
{
    if (empty($to)) return;  // Skip if no email provided

    $fromAddress = $mailConfig['from_address'] ?? 'noreply@simplepay.local';
    $fromName = $mailConfig['from_name'] ?? 'SimplePay Alerts';
    $subjectPrefix = $mailConfig['subject_prefix'] ?? '[SimplePay] ';

    $subject = $subjectPrefix . ($prediction['is_fraudulent'] ? 'Potential Fraud Detected' : 'Transaction Notification');
    $statusText = $prediction['is_fraudulent'] ? 'A high-risk transaction was detected on your account.' : 'Your transaction was successfully recorded.';
    $riskText = $prediction['risk_level'] ? '<strong>Risk level:</strong> ' . htmlspecialchars($prediction['risk_level']) . '<br>' : '';
    $amountText = isset($transaction['amount']) ? '<strong>Amount:</strong> GHS ' . number_format((float)$transaction['amount'], 2) . '<br>' : '';
    $transactionId = htmlspecialchars($transaction['transaction_id'] ?? '');

    $statusBadge = $prediction['is_fraudulent'] 
        ? '<span style="display: inline-block; background-color: #dc2626; color: white; padding: 6px 12px; border-radius: 20px; font-size: 12px; font-weight: bold; margin-bottom: 20px;">⚠️ HIGH RISK</span>'
        : '<span style="display: inline-block; background-color: #16a34a; color: white; padding: 6px 12px; border-radius: 20px; font-size: 12px; font-weight: bold; margin-bottom: 20px;">✓ VERIFIED</span>';
    
    $backgroundColor = $prediction['is_fraudulent'] ? '#fef2f2' : '#f0fdf4';
    $borderColor = $prediction['is_fraudulent'] ? '#fecaca' : '#bbf7d0';

    $message = '<!DOCTYPE html>';
    $message .= '<html style="margin: 0; padding: 0;">';
    $message .= '<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>';
    $message .= '<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, \'Helvetica Neue\', Arial, sans-serif; background-color: #f9fafb; color: #374151;">';
    
    // Header
    $message .= '<div style="background: linear-gradient(135deg, #1e40af 0%, #1a365d 100%); padding: 30px 20px; text-align: center;">';
    $message .= '<h1 style="margin: 0; color: white; font-size: 28px; font-weight: bold;">SimplePay</h1>';
    $message .= '<p style="margin: 5px 0 0 0; color: #dbeafe; font-size: 14px;">Transaction Notification</p>';
    $message .= '</div>';
    
    // Main content
    $message .= '<div style="max-width: 600px; margin: 0 auto; padding: 30px 20px;">';
    
    // Status badge
    $message .= '<div style="background-color: ' . $backgroundColor . '; border-left: 4px solid ' . $borderColor . '; padding: 20px; border-radius: 8px; margin-bottom: 25px;">';
    $message .= $statusBadge;
    $message .= '<p style="margin: 10px 0 0 0; font-size: 16px; color: #111827; line-height: 1.5;">' . $statusText . '</p>';
    $message .= '</div>';
    
    // Transaction details card
    $message .= '<div style="background-color: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 25px; margin-bottom: 25px;">';
    $message .= '<h3 style="margin: 0 0 20px 0; color: #1a365d; font-size: 16px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">Transaction Details</h3>';
    
    // Transaction ID
    $message .= '<div style="display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid #f3f4f6;">';
    $message .= '<span style="color: #6b7280; font-size: 14px;">Transaction ID</span>';
    $message .= '<span style="color: #1a365d; font-weight: 600; font-family: monospace; font-size: 13px;">' . $transactionId . '</span>';
    $message .= '</div>';
    
    // Amount
    if (isset($transaction['amount'])) {
        $message .= '<div style="display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid #f3f4f6;">';
        $message .= '<span style="color: #6b7280; font-size: 14px;">Amount</span>';
        $message .= '<span style="color: #059669; font-weight: bold; font-size: 16px;">GHS ' . number_format((float)$transaction['amount'], 2) . '</span>';
        $message .= '</div>';
    }
    
    // Transaction type
    $message .= '<div style="display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid #f3f4f6;">';
    $message .= '<span style="color: #6b7280; font-size: 14px;">Type</span>';
    $message .= '<span style="color: #1a365d; font-weight: 500;">' . htmlspecialchars($transaction['transaction_type'] ?? 'N/A') . '</span>';
    $message .= '</div>';
    
    // Risk level (if fraudulent)
    if ($prediction['is_fraudulent']) {
        $message .= '<div style="display: flex; justify-content: space-between; padding: 12px 0;">';
        $message .= '<span style="color: #6b7280; font-size: 14px;">Risk Level</span>';
        $message .= '<span style="color: #dc2626; font-weight: bold;">' . htmlspecialchars($prediction['risk_level'] ?? 'High') . '</span>';
        $message .= '</div>';
    }
    
    // Timestamp
    $message .= '<div style="display: flex; justify-content: space-between; padding: 12px 0;">';
    $message .= '<span style="color: #6b7280; font-size: 14px;">Date & Time</span>';
    $message .= '<span style="color: #1a365d; font-weight: 500;">' . htmlspecialchars($transaction['transaction_time'] ?? '') . '</span>';
    $message .= '</div>';
    
    $message .= '</div>';
    
    // Alert message for fraud
    if ($prediction['is_fraudulent']) {
        $message .= '<div style="background-color: #fef2f2; border-left: 4px solid #dc2626; padding: 16px; border-radius: 6px; margin-bottom: 25px;">';
        $message .= '<p style="margin: 0; color: #991b1b; font-size: 14px; line-height: 1.6;">';
        $message .= '<strong>⚠️ Action Required:</strong> If you did not authorize this transaction, please contact our support team immediately to secure your account.';
        $message .= '</p>';
        $message .= '</div>';
    }
    
    // Action button
    $message .= '<div style="text-align: center; margin: 30px 0;">';
    $message .= '<a href="' . htmlspecialchars(rtrim((string) (getenv('APP_BASE_URL') ?: 'https://localhost/smartDetector/app'), '/')) . '" style="display: inline-block; background-color: #1e40af; color: white; padding: 12px 30px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px;">View in Dashboard</a>';
    $message .= '</div>';
    
    $message .= '</div>';
    
    // Footer
    $message .= '<div style="background-color: #f3f4f6; border-top: 1px solid #e5e7eb; padding: 25px 20px; text-align: center;">';
    $message .= '<p style="margin: 0 0 10px 0; color: #6b7280; font-size: 12px;">SimplePay - Secure Transaction Management</p>';
    $message .= '<p style="margin: 0; color: #9ca3af; font-size: 11px;">This is an automated email. Please do not reply to this message.</p>';
    $message .= '<p style="margin: 10px 0 0 0; color: #d1d5db; font-size: 10px;">© 2026 SimplePay. All rights reserved.</p>';
    $message .= '</div>';
    
    $message .= '</body>';
    $message .= '</html>';

    $autoload = __DIR__ . '/vendor/autoload.php';
    $phpmailerSrc = __DIR__ . '/../app/PHPMailer/src';

    if (file_exists($autoload)) {
        require_once $autoload;
    } elseif (file_exists($phpmailerSrc . '/PHPMailer.php')) {
        require_once $phpmailerSrc . '/Exception.php';
        require_once $phpmailerSrc . '/PHPMailer.php';
        require_once $phpmailerSrc . '/SMTP.php';
    }

    if (class_exists('\PHPMailer\PHPMailer\PHPMailer')) {
        try {
            $mail = new \PHPMailer\PHPMailer\PHPMailer(true);
            $mail->CharSet = 'UTF-8';

            $smtp = $mailConfig['smtp'] ?? [];
            if (!empty($smtp['enabled'])) {
                $mail->isSMTP();
                $mail->Host = $smtp['host'] ?? 'smtp.gmail.com';
                $mail->SMTPAuth = true;
                $mail->Username = $smtp['username'] ?? '';
                $mail->Password = $smtp['password'] ?? '';
                $mail->SMTPSecure = $smtp['secure'] ?? \PHPMailer\PHPMailer\PHPMailer::ENCRYPTION_STARTTLS;
                $mail->Port = (int)($smtp['port'] ?? 587);
                $mail->SMTPOptions = array(
                    'ssl' => array(
                        'verify_peer' => false,
                        'verify_peer_name' => false,
                        'allow_self_signed' => true
                    )
                );
            }

            $mail->setFrom($fromAddress, $fromName);
            $mail->addAddress($to);
            $mail->Subject = $subject;
            $mail->isHTML(true);
            $mail->Body = $message;
            $mail->AltBody = strip_tags($message);
            $mail->send();
            $sendMessage = 'Email sent to ' . $to . ' for transaction ' . $transactionId;
            error_log($sendMessage);
            return ['success' => true, 'method' => 'phpmailer', 'message' => $sendMessage];
        } catch (Exception $e) {
            $errorMessage = 'PHPMailer error for ' . $to . ': ' . $e->getMessage();
            error_log($errorMessage);
            return ['success' => false, 'method' => 'phpmailer', 'message' => $errorMessage];
        }
    }

    // Fallback: use native PHP mail()
    $fallback = sendViaPhpMail($to, $fromAddress, $fromName, $subject, $message);
    return $fallback;
}

function sendViaPhpMail(string $to, string $fromAddress, string $fromName, string $subject, string $message)
{
    $headers = "MIME-Version: 1.0\r\n";
    $headers .= "Content-Type: text/html; charset=UTF-8\r\n";
    $headers .= "From: " . $fromName . " <" . $fromAddress . ">\r\n";
    $sent = @mail($to, $subject, $message, $headers);
    $messageText = $sent ? 'Email sent via PHP mail() to ' . $to : 'PHP mail() failed for ' . $to;
    error_log($messageText);
    return ['success' => $sent, 'method' => 'php_mail', 'message' => $messageText];
}
