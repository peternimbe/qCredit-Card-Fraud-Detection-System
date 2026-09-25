<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, Authorization');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(204);
    exit;
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['error' => 'Method not allowed']);
    exit;
}

$config = require __DIR__ . '/config.php';
$input = json_decode(file_get_contents('php://input'), true);
if (json_last_error() !== JSON_ERROR_NONE) {
    http_response_code(400);
    echo json_encode(['error' => 'Invalid JSON payload']);
    exit;
}

$name = trim($input['name'] ?? '');
$email = trim($input['email'] ?? '');
$accountNumber = trim($input['account_number'] ?? '');
$password = $input['password'] ?? '';

if ($name === '' || $email === '' || $accountNumber === '' || $password === '') {
    http_response_code(400);
    echo json_encode(['error' => 'Name, email, account number and password are required']);
    exit;
}

if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
    http_response_code(400);
    echo json_encode(['error' => 'Please enter a valid email address']);
    exit;
}

if (!preg_match('/^[0-9]{6,20}$/', $accountNumber)) {
    http_response_code(400);
    echo json_encode(['error' => 'Account number must be 6-20 digits']);
    exit;
}

if (strlen($password) < 8) {
    http_response_code(400);
    echo json_encode(['error' => 'Password must be at least 8 characters']);
    exit;
}

$dsn = sprintf(
    'mysql:host=%s;port=%d;dbname=%s;charset=%s',
    $config['db']['host'],
    $config['db']['port'],
    $config['db']['dbname'],
    $config['db']['charset']
);

try {
    $pdo = new PDO($dsn, $config['db']['username'], $config['db']['password'], db_options($config['db']));

    $stmt = $pdo->prepare('SELECT id FROM users WHERE email = :email OR account_number = :account_number');
    $stmt->execute([
        ':email' => $email,
        ':account_number' => $accountNumber,
    ]);
    if ($stmt->fetch()) {
        http_response_code(409);
        echo json_encode(['error' => 'Email or account number already registered']);
        exit;
    }

    $passwordHash = password_hash($password, PASSWORD_DEFAULT);
    $insert = $pdo->prepare('INSERT INTO users (name, email, account_number, password_hash, created_at) VALUES (:name, :email, :account_number, :password_hash, NOW())');
    $insert->execute([
        ':name' => $name,
        ':email' => $email,
        ':account_number' => $accountNumber,
        ':password_hash' => $passwordHash,
    ]);

    // Send welcome email
    sendWelcomeEmail($config['mail'] ?? [], $email, $name);

    http_response_code(201);
    echo json_encode(['status' => 'success', 'message' => 'Account created successfully']);
    exit;
} catch (PDOException $e) {
    error_log('Signup error: ' . $e->getMessage());
    http_response_code(500);
    echo json_encode(['error' => 'Unable to create account. Please try again later.']);
    exit;
}

function sendWelcomeEmail(array $mailConfig, string $email, string $name)
{
    if (empty($email)) return;

    $fromAddress = $mailConfig['from_address'] ?? 'noreply@simplepay.local';
    $fromName = $mailConfig['from_name'] ?? 'SimplePay';
    $subject = ($mailConfig['subject_prefix'] ?? '[SimplePay] ') . 'Welcome to SimplePay!';

    $message = '<html><body style="font-family: Arial, sans-serif; color: #333;">';
    $message .= '<div style="max-width: 600px; margin: 0 auto; padding: 20px;">';
    $message .= '<h2 style="color: #1a365d;">Welcome to SimplePay, ' . htmlspecialchars($name) . '!</h2>';
    $message .= '<p>Your account has been created successfully.</p>';
    $message .= '<p><strong>Your login email:</strong> ' . htmlspecialchars($email) . '</p>';
    $message .= '<p>You can now log in and start using SimplePay to send money, make payments, and more.</p>';
    $message .= '<p style="margin-top: 30px; color: #666; font-size: 12px;">If you did not create this account, please contact support.</p>';
    $message .= '</div>';
    $message .= '</body></html>';

    $autoload = __DIR__ . '/vendor/autoload.php';
    if (file_exists($autoload)) {
        require_once $autoload;
        try {
            $mail = new PHPMailer\PHPMailer\PHPMailer(true);
            $mail->CharSet = 'UTF-8';

            $smtp = $mailConfig['smtp'] ?? [];
            if (!empty($smtp['enabled']) && !empty($smtp['host'])) {
                $mail->isSMTP();
                $mail->Host = $smtp['host'];
                $mail->Port = (int)($smtp['port'] ?? 587);
                $mail->SMTPSecure = $smtp['secure'] ?? 'tls';
                $mail->SMTPAuth = !empty($smtp['auth']);
                if (!empty($smtp['username'])) $mail->Username = $smtp['username'];
                if (!empty($smtp['password'])) $mail->Password = $smtp['password'];
            }

            $mail->setFrom($fromAddress, $fromName);
            $mail->addAddress($email);
            $mail->Subject = $subject;
            $mail->isHTML(true);
            $mail->Body = $message;
            $mail->AltBody = strip_tags($message);
            $mail->send();
            error_log('Welcome email sent to ' . $email);
        } catch (Exception $e) {
            error_log('PHPMailer signup error for ' . $email . ': ' . $e->getMessage());
            // Fallback to PHP mail()
            $headers = "MIME-Version: 1.0\r\n";
            $headers .= "Content-Type: text/html; charset=UTF-8\r\n";
            $headers .= "From: " . $fromName . " <" . $fromAddress . ">\r\n";
            @mail($email, $subject, $message, $headers);
        }
    } else {
        // Use PHP mail() if PHPMailer not available
        $headers = "MIME-Version: 1.0\r\n";
        $headers .= "Content-Type: text/html; charset=UTF-8\r\n";
        $headers .= "From: " . $fromName . " <" . $fromAddress . ">\r\n";
        @mail($email, $subject, $message, $headers);
    }
}
