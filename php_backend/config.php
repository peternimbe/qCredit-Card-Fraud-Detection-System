<?php
// Configuration is read from environment variables (Render / Docker) with XAMPP-friendly defaults.
// For local overrides create php_backend/config.local.php (git-ignored) returning a partial array, e.g.
//   return ['mail' => ['smtp' => ['username' => 'me@gmail.com', 'password' => '...']]];

if (!function_exists('env_value')) {
    function env_value(string $name, $default = null)
    {
        $value = getenv($name);
        return ($value === false || $value === '') ? $default : $value;
    }
}

if (!function_exists('db_options')) {
    /** PDO options shared by every endpoint; enables TLS when DB_SSL=1 (managed MySQL on Render etc.). */
    function db_options(array $db): array
    {
        $options = [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES => false,
        ];
        if (!empty($db['ssl']) && defined('PDO::MYSQL_ATTR_SSL_VERIFY_SERVER_CERT')) {
            $options[PDO::MYSQL_ATTR_SSL_VERIFY_SERVER_CERT] = false;
            $options[PDO::MYSQL_ATTR_SSL_CA] = '/etc/ssl/certs/ca-certificates.crt';
        }
        return $options;
    }
}


$config = [
    'db' => [
        'host' => env_value('DB_HOST', '127.0.0.1'),
        'port' => (int) env_value('DB_PORT', 3306),
        'dbname' => env_value('DB_NAME', 'fraud_detection'),
        'username' => env_value('DB_USER', 'root'),
        'password' => env_value('DB_PASSWORD', ''),
        'charset' => 'utf8mb4',
        // Managed MySQL providers usually require TLS: set DB_SSL=1 (certificate is not pinned).
        'ssl' => in_array(strtolower((string) env_value('DB_SSL', '0')), ['1', 'true', 'yes'], true),
    ],

    // Python model API (scores a transaction before it is stored)
    'model_api_url' => rtrim((string) env_value('MODEL_API_URL', 'http://localhost:8000'), '/') . '/predict_named',

    'mail' => [
        'from_address' => env_value('MAIL_FROM_ADDRESS', 'noreply@simplepay.local'),
        'from_name' => env_value('MAIL_FROM_NAME', 'SimplePay Alerts'),
        'subject_prefix' => env_value('MAIL_SUBJECT_PREFIX', '[SimplePay] '),
        'smtp' => [
            // SMTP is only enabled when a password is supplied, so nothing is sent by accident.
            'enabled' => env_value('SMTP_PASSWORD') !== null,
            'host' => env_value('SMTP_HOST', 'smtp.gmail.com'),
            'port' => (int) env_value('SMTP_PORT', 587),
            'secure' => env_value('SMTP_SECURE', 'tls'),
            'auth' => true,
            'username' => env_value('SMTP_USERNAME', ''),
            'password' => env_value('SMTP_PASSWORD', ''),
        ],
    ],
];

$localFile = __DIR__ . '/config.local.php';
if (is_file($localFile)) {
    $config = array_replace_recursive($config, require $localFile);
}

return $config;
