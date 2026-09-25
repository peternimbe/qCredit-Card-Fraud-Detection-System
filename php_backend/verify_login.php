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

$email = trim(strtolower($input['email'] ?? ''));
$password = $input['password'] ?? '';

if ($email === '' || $password === '') {
    http_response_code(400);
    echo json_encode(['error' => 'Email and password are required']);
    exit;
}

// Static admin fallback
const ADMIN_EMAIL = 'admin@simplepay.local';
const ADMIN_PASSWORD = 'simplepay123';

if ($email === ADMIN_EMAIL && $password === ADMIN_PASSWORD) {
    echo json_encode(['status' => 'ok', 'user' => ['email' => $email, 'name' => 'Administrator', 'is_admin' => true]]);
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

    // Select only known columns; some installations may not have `is_admin` column.
    $stmt = $pdo->prepare('SELECT id, name, email, password_hash FROM users WHERE email = :email LIMIT 1');
    $stmt->execute([':email' => $email]);
    $user = $stmt->fetch();

    if (!$user) {
        http_response_code(401);
        echo json_encode(['error' => 'Invalid email or password']);
        exit;
    }

    if (!isset($user['password_hash']) || !password_verify($password, $user['password_hash'])) {
        http_response_code(401);
        echo json_encode(['error' => 'Invalid email or password']);
        exit;
    }

    // If the `is_admin` column is present, include it; otherwise default to false.
    $isAdmin = false;
    if (is_array($user) && array_key_exists('is_admin', $user)) {
        $isAdmin = (bool)$user['is_admin'];
    }

    echo json_encode(['status' => 'ok', 'user' => ['email' => $user['email'], 'name' => $user['name'] ?? '', 'is_admin' => $isAdmin]]);
    exit;
} catch (PDOException $e) {
    error_log('Login error: ' . $e->getMessage());
    http_response_code(500);
    echo json_encode(['error' => 'Unable to verify credentials']);
    exit;
}

