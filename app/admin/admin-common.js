const ADMIN_STORAGE = {
    transactions: 'admin_transaction_feed',
    alerts: 'admin_alert_history',
    settings: 'admin_model_settings'
};

// Set window.SMARTDETECTOR_API_URL in ../runtime-config.js (generated from the API_URL env var on Render)
const BACKEND_API = (window.SMARTDETECTOR_API_URL || 'http://localhost:8000').replace(/\/+$/, '');
const PHP_BACKEND_API = '../../php_backend/transaction_api.php'; // Update this to your PHP endpoint path

const defaultModelSettings = {
    alertThreshold: 75,
    liveMonitoring: true,
    explainability: true,
    ensembleMode: 'Weighted Voting',
    fraudSensitivity: 'High'
};

const DEFAULT_TRANSACTIONS = [
    { id: 'TX-1001', time: '21:05:12', amount: 1200, merchant: 'GlobalMart', merchantRisk: 82, type: 'Online Payment', status: 'Fraud', note: 'High-risk merchant', riskScore: 88, timestamp: Date.now() - 180000 },
    { id: 'TX-1002', time: '21:04:55', amount: 45.2, merchant: 'QuickEats', merchantRisk: 20, type: 'Food Delivery', status: 'Safe', note: 'Normal purchase', riskScore: 12, timestamp: Date.now() - 240000 },
    { id: 'TX-1003', time: '21:04:30', amount: 890, merchant: 'AutoZone', merchantRisk: 45, type: 'Auto Parts', status: 'Safe', note: 'Routine purchase', riskScore: 45, timestamp: Date.now() - 300000 },
    { id: 'TX-1004', time: '21:04:10', amount: 2450, merchant: 'LuxuryFlights', merchantRisk: 95, type: 'Travel Booking', status: 'Fraud', note: 'High spend + high-risk provider', riskScore: 94, timestamp: Date.now() - 360000 }
];

const MOCK_MERCHANTS = [
    { name: 'MetroPay', risk: 62, category: 'Utilities' },
    { name: 'NovaShop', risk: 40, category: 'Retail' },
    { name: 'FastRide', risk: 55, category: 'Transport' },
    { name: 'DataWave', risk: 75, category: 'Telecom' },
    { name: 'Petra Travel', risk: 89, category: 'Travel' },
    { name: 'QuickEats', risk: 28, category: 'Food' },
    { name: 'Pulse Health', risk: 34, category: 'Healthcare' },
    { name: 'GlobalMart', risk: 82, category: 'Retail' },
    { name: 'Secure Loans', risk: 91, category: 'Finance' }
];

const TRANSACTION_TYPES = ['Online Payment', 'Wire Transfer', 'Cash Withdrawal', 'Subscription', 'Grocery', 'Travel Booking', 'Food Delivery'];

function getStored(key, fallback) {
    try {
        const raw = localStorage.getItem(key);
        if (!raw) return fallback;
        return JSON.parse(raw);
    } catch (err) {
        console.warn('Invalid stored JSON for', key, err);
        return fallback;
    }
}

function saveStored(key, value) {
    localStorage.setItem(key, JSON.stringify(value));
}

function loadSettings() {
    return getStored(ADMIN_STORAGE.settings, defaultModelSettings);
}

function saveSettings(settings) {
    saveStored(ADMIN_STORAGE.settings, settings);
}

function loadTransactions() {
    const tx = getStored(ADMIN_STORAGE.transactions, DEFAULT_TRANSACTIONS);
    if (!tx || !Array.isArray(tx) || tx.length === 0) {
        saveTransactions(DEFAULT_TRANSACTIONS);
        return DEFAULT_TRANSACTIONS;
    }
    return tx;
}

function saveTransactions(value) {
    saveStored(ADMIN_STORAGE.transactions, value.slice(0, 50));
}

function loadAlerts() {
    return getStored(ADMIN_STORAGE.alerts, []);
}

function saveAlerts(alerts) {
    saveStored(ADMIN_STORAGE.alerts, alerts.slice(0, 100));
}

function formatCurrency(value) {
    return 'GHS ' + value.toFixed(2);
}

function formatTime(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' • ' + date.toLocaleDateString();
}

function friendlyFeatureName(feature) {
    const raw = String(feature || 'feature');
    const labelMap = {
        dest_balance_known: 'Recipient balance available',
        hour_of_day: 'Time of day',
        is_night: 'Night-time transaction',
        orig_balance_error: 'Sender balance mismatch',
        dest_balance_error: 'Recipient balance mismatch',
        amount_to_balance_ratio: 'Share of balance being moved',
        orig_drained: 'Account emptied',
        amount_exceeds_balance: 'Amount exceeds available balance',
        dest_empty_before: 'Recipient account was empty',
        dest_unchanged: 'Recipient balance did not change',
        step: 'Transaction sequence position',
        Time: 'Transaction timing',
        amount: 'Amount',
        oldbalanceOrg: 'Originating balance before transaction',
        newbalanceOrig: 'Originating balance after transaction',
        oldbalanceDest: 'Receiving account balance before transaction',
        newbalanceDest: 'Receiving account balance after transaction',
        orig_amount_mean: 'Customer normal transaction amount',
        orig_amount_std: 'Customer spending variability',
        time_since_prev: 'Time since previous transaction',
        merchant_risk: 'Merchant risk',
        time_hour: 'Time of day',
        tx_count_24h: 'Recent activity',
        is_unusual_amount: 'Unusual amount flag',
        auth_failures: 'Authentication failures',
        account_age_days: 'Account age',
        device_account_count: 'Accounts using this device',
        ip_account_count: 'Accounts using this network address',
        beneficiary_tx_count: 'Previous transactions with beneficiary',
        merchant_tx_count: 'Previous transactions with merchant',
        is_new_device: 'New device',
        is_new_ip: 'New network address',
        is_new_beneficiary: 'New beneficiary',
        is_new_merchant: 'New merchant',
        rapid_withdrawal_count: 'Rapid withdrawal activity',
        customer_category_deviation: 'Spending category change',
        location_available: 'Location data available',
        location_latitude: 'Transaction latitude',
        location_longitude: 'Transaction longitude',
        high_risk_location_flag: 'High-risk location',
        location_change_distance_km: 'Distance from previous transaction',
        impossible_travel_flag: 'Impossible travel pattern',
        type_PAYMENT: 'Payment type',
        type_CASH_OUT: 'Cash out',
        type_DEBIT: 'Debit',
        type_TRANSFER: 'Transfer',
        merchant_cat_retail: 'Retail category',
        merchant_cat_restaurant: 'Restaurant category',
        merchant_cat_grocery: 'Grocery category',
        merchant_cat_travel: 'Travel category',
        merchant_cat_utilities: 'Utilities category',
        country_US: 'Country: US',
        country_GB: 'Country: GB',
        country_IN: 'Country: IN',
        country_DE: 'Country: DE',
        country_FR: 'Country: FR',
        country_CN: 'Country: CN',
        country_NG: 'Country: NG',
        country_JP: 'Country: JP',
        country_RU: 'Country: RU',
        transaction_channel_BANK_TRANSFER: 'Bank transfer channel',
        transaction_channel_ONLINE: 'Online payment channel',
        transaction_channel_POS: 'Point-of-sale channel'
    };

    return labelMap[raw] || raw
        .replace(/_/g, ' ')
        .replace(/type /i, 'Type: ')
        .replace(/merchant cat /i, 'Category: ')
        .replace(/country /i, 'Country: ')
        .replace(/\b\w/g, (char) => char.toUpperCase());
}

function describeRiskSignal(feature, item) {
    const label = (item && item.label) || friendlyFeatureName(feature);
    const direction = String(item && (item.direction || item.impact_direction) || '').toLowerCase();
    const contribution = Number(item && item.contribution || 0);
    const raisesRisk = direction.includes('increase') || direction.includes('higher') || contribution > 0;
    return { label, raisesRisk };
}

function isGenericExplanation(tx) {
    const reason = String(tx && tx.explanation && tx.explanation.reason || tx && tx.reason || '');
    return /^important risk factors are/i.test(reason) || /fallback explanation generated from model feature importance/i.test(reason);
}

function observedSignalStrength(feature, value) {
    const numericValue = Math.abs(Number(value) || 0);
    if (feature === 'merchant_risk') return Math.min(100, Math.round(numericValue * 100));
    if (feature === 'time_hour') return numericValue >= 2 && numericValue <= 6 ? 90 : 15;
    if (feature === 'amount' || feature === 'oldbalanceOrg' || feature === 'newbalanceOrig') return Math.min(100, Math.round(numericValue / 2000 * 100));
    if (feature === 'amount_z') return Math.min(100, Math.round(numericValue * 25));
    if (feature === 'tx_count_24h' || feature === 'rapid_withdrawal_count') return Math.min(100, Math.round(numericValue * 25));
    if (/^is_|auth_failures|_deviation$/.test(feature)) return numericValue > 0 ? 85 : 10;
    if (/account_count|tx_count|beneficiary_tx_count|merchant_tx_count/.test(feature)) return Math.min(100, Math.round(numericValue * 20));
    return Math.min(100, Math.max(10, Math.round(numericValue)));
}

function getObservedFeatureValue(tx, feature) {
    const snapshot = tx && tx.feature_snapshot ? tx.feature_snapshot : {};
    if (snapshot[feature] !== undefined && snapshot[feature] !== null) return snapshot[feature];
    if (feature === 'amount') return tx && tx.amount;
    if (feature === 'oldbalanceOrg') return Math.abs(Number(tx && tx.amount || 0)) * 2;
    if (feature === 'newbalanceOrig') return Math.abs(Number(tx && tx.amount || 0)) * 1.4;
    if (feature === 'merchant_risk') return Number(tx && (tx.merchantRisk || tx.merchant_risk) || 0);
    if (feature === 'time_hour') return tx && tx.timestamp ? new Date(tx.timestamp).getHours() : 12;
    if (feature === 'is_unusual_amount') return Number(tx && tx.amount || 0) > 2000 ? 1 : 0;
    if (feature === 'type_CASH_OUT') return /withdraw|cash.?out/i.test(String(tx && tx.type || '')) ? 1 : 0;
    if (feature === 'type_TRANSFER') return /send|transfer|wire/i.test(String(tx && tx.type || '')) ? 1 : 0;
    return 0;
}

function calculateRiskScore(tx, settings) {
    const normalizedAmount = Math.min(100, Math.abs(tx.amount) / 20);
    const merchantFactor = Number(tx.merchantRisk || 0) * 0.4;
    const typeFactor = String(tx.type || '').includes('Transfer') || String(tx.type || '').includes('Booking') ? 10 : 0;
    const timeFactor = tx.isNight ? 15 : 0;
    const sensitivity = settings.fraudSensitivity === 'High' ? 1.1 : settings.fraudSensitivity === 'Low' ? 0.9 : 1.0;
    return Math.min(100, Math.round((normalizedAmount + merchantFactor + typeFactor + timeFactor) * sensitivity));
}

const ADMIN_TYPE_MAP = {
    'wire transfer': 'TRANSFER', 'cash withdrawal': 'CASH_OUT', 'cash out': 'CASH_OUT', 'withdraw': 'CASH_OUT',
    'send': 'TRANSFER', 'transfer': 'TRANSFER', 'deposit': 'CASH_IN', 'debit': 'DEBIT'
};

// Named payload for POST /predict_named (see GET /feature-schema on the API). No PCA, no invented features.
function buildNamedPayload(tx) {
    const when = new Date(tx.timestamp || Date.now());
    const amount = Math.abs(Number(tx.amount) || 0);
    const typeKey = String(tx.type || tx.transaction_type || 'payment').toLowerCase();
    const finite = (value) => (Number.isFinite(Number(value)) && value !== null && value !== '' ? Number(value) : null);
    return {
        transaction_type: ADMIN_TYPE_MAP[typeKey] || 'PAYMENT',
        amount,
        oldbalanceOrg: finite(tx.balance_before ?? tx.oldbalanceOrg),
        newbalanceOrig: finite(tx.balance_after ?? tx.newbalanceOrig),
        oldbalanceDest: finite(tx.destination_balance_before ?? tx.oldbalanceDest),
        newbalanceDest: finite(tx.destination_balance_after ?? tx.newbalanceDest),
        hour_of_day: when.getHours(),
        timestamp: when.getTime(),
        tx_count_24h: tx.frequency ?? null,
        country: tx.country || null
    };
}

async function predictFraudBackend(tx) {
    try {
        const payload = buildNamedPayload(tx);
        const response = await fetch(`${BACKEND_API}/predict_named`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            console.warn('Backend prediction failed, using fallback calculation');
            return null;
        }

        const data = await response.json();
        const prob = Number(data.fraud_probability ?? 0);
        const riskScore = Number.isFinite(data.risk_score) ? data.risk_score : Math.min(100, Math.max(0, Math.round(prob * 100)));
        const status = (data.is_fraudulent || riskScore >= loadSettings().alertThreshold) ? 'Fraud' : 'Safe';

        return {
            riskScore,
            status,
            riskLevel: data.risk_level || (riskScore > 80 ? 'High Risk' : riskScore > 60 ? 'Medium Risk' : 'Low Risk'),
            contextFlags: data.context_flags || [],
            explanation: data.explanation || {},
            modelScores: data.model_scores || {}
        };
    } catch (err) {
        console.warn('Backend call failed:', err);
        return null;
    }
}

async function fetchModelInfo() {
    // Fetch model info from backend
    try {
        const response = await fetch(`${BACKEND_API}/model-info`);
        if (!response.ok) {
            console.warn('Failed to fetch model info');
            return null;
        }
        return await response.json();
    } catch (err) {
        console.warn('Model info fetch failed:', err);
        return null;
    }
}

function buildXAIExplainability(tx) {
    const explanation = tx && tx.explanation ? tx.explanation : null;
    const impacts = explanation && Array.isArray(explanation.feature_impacts) ? explanation.feature_impacts : null;
    if (impacts && impacts.length) {
        return impacts.slice(0, 5).map(item => {
            const contribution = Number(item.contribution ?? item.value ?? 0);
            const signal = describeRiskSignal(item.feature || 'feature', item);
            const featureValue = getObservedFeatureValue(tx, item.feature);
            const value = isGenericExplanation(tx)
                ? observedSignalStrength(item.feature, featureValue)
                : Math.min(100, Math.max(5, Math.round(item.impact_pct != null ? Number(item.impact_pct) : Math.abs(contribution) * 100)));
            return {
                label: signal.label,
                value
            };
        });
    }

    return [];
}

function buildRiskReason(tx) {
    const explanation = tx && tx.explanation ? tx.explanation : null;
    const impacts = explanation && Array.isArray(explanation.feature_impacts) ? explanation.feature_impacts : [];
    if (impacts.length) {
        if (isGenericExplanation(tx)) {
            const observed = impacts
                .map(item => ({
                    label: friendlyFeatureName(item.feature || 'feature').toLowerCase(),
                    value: observedSignalStrength(item.feature || 'feature', getObservedFeatureValue(tx, item.feature))
                }))
                .filter(item => item.value >= 50)
                .sort((left, right) => right.value - left.value)
                .slice(0, 3)
                .map(item => item.label);
            if (observed.length) return `The transaction shows ${joinNatural(observed)}`;
        }
        const strongest = impacts
            .map(item => ({ item, signal: describeRiskSignal(item.feature || 'feature', item) }))
            .sort((left, right) => Math.abs(Number(right.item.contribution || 0)) - Math.abs(Number(left.item.contribution || 0)))
            .slice(0, 3);
        const riskSignals = strongest.filter(entry => entry.signal.raisesRisk).map(entry => entry.signal.label.toLowerCase());
        const protectiveSignals = strongest.filter(entry => !entry.signal.raisesRisk).map(entry => entry.signal.label.toLowerCase());
        const status = String(tx && (tx.status || tx.riskLevel) || '').toLowerCase();

        if (riskSignals.length) {
            const signalText = joinNatural(riskSignals);
            return status.includes('safe') || status.includes('low')
                ? `The transaction remains low risk, although the model noticed ${signalText}`
                : `The model flagged this transaction because of ${signalText}`;
        }
        if (protectiveSignals.length) {
            return `The model found no major risk signal; the strongest normality indicators were ${joinNatural(protectiveSignals)}`;
        }
    }
    if (tx && tx.reason && !/^important risk factors are/i.test(tx.reason)) {
        return tx.reason;
    }

    const reasons = [];
    if (Number(tx && tx.amount || 0) > 2000) reasons.push('Unusually large amount');
    if (Number(tx && tx.merchantRisk || 0) > 75) reasons.push('High-risk merchant');
    if (tx && tx.isNight) reasons.push('Unusual transaction time');
    if (tx && tx.frequency && tx.frequency > 3) reasons.push('Multiple rapid transactions');
    if (reasons.length === 0) reasons.push('Model confidence is consistent with the current feature profile');
    return reasons.join(' and ');
}

function joinNatural(items) {
    if (items.length <= 1) return items[0] || 'the current transaction profile';
    if (items.length === 2) return `${items[0]} and ${items[1]}`;
    return `${items.slice(0, -1).join(', ')}, and ${items[items.length - 1]}`;
}

function createMockTransaction() {
    const merchant = MOCK_MERCHANTS[Math.floor(Math.random() * MOCK_MERCHANTS.length)];
    const type = TRANSACTION_TYPES[Math.floor(Math.random() * TRANSACTION_TYPES.length)];
    const amount = Number((Math.random() * (merchant.risk > 80 ? 7000 : 1200) + 15).toFixed(2));
    const now = Date.now();
    const hour = new Date(now).getHours();
    const isNight = hour < 6 || hour > 22;
    // Simulated account context: most customers keep a healthy cushion; ~8% empty the account.
    const drains = Math.random() < 0.08;
    const balanceBefore = Number((drains ? amount : amount * (1.3 + Math.random() * 5)).toFixed(2));
    const balanceAfter = Number(Math.max(0, balanceBefore - amount).toFixed(2));
    const tx = {
        id: 'TX-' + Math.floor(Math.random() * 999999),
        time: new Date(now).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        amount,
        merchant: merchant.name,
        merchantRisk: merchant.risk,
        type: type,
        note: `${type} at ${merchant.name}`,
        timestamp: now,
        balance_before: balanceBefore,
        balance_after: balanceAfter,
        isNight,
        frequency: Math.floor(Math.random() * 5),
        riskScore: 0,
        status: 'Pending'
    };
    return tx;
}

async function createAndPredictTransaction() {
    // Create a transaction and get fraud prediction from backend (or fallback to local calculation)
    const tx = createMockTransaction();
    const settings = loadSettings();
    
    // Try to get prediction from backend
    const prediction = await predictFraudBackend(tx);
    
    if (prediction) {
        tx.riskScore = prediction.riskScore;
        tx.status = prediction.status;
        tx.riskLevel = prediction.riskLevel;
        tx.explanation = prediction.explanation;
        tx.modelScores = prediction.modelScores;
    } else {
        // Fallback to local calculation if backend unavailable
        tx.riskScore = calculateRiskScore(tx, settings);
        tx.status = tx.riskScore >= settings.alertThreshold ? 'Fraud' : 'Safe';
        tx.riskLevel = tx.riskScore > 80 ? 'High Risk' : tx.riskScore > 60 ? 'Medium Risk' : 'Low Risk';
    }

    tx.php_save_response = await storeTransactionToPHP(tx);
    return tx;
}

async function storeTransactionToPHP(tx) {
    try {
        const payload = {
            transaction_id: tx.id,
            transaction_type: tx.type,
            amount: tx.amount,
            oldbalanceOrg: tx.balance_before ?? null,
            newbalanceOrig: tx.balance_after ?? null,
            timestamp: tx.timestamp,
            description: tx.note,
            recipient: tx.merchant,
            merchant: tx.merchant,
            Time: tx.timestamp / 1000,
            risk_score: tx.riskScore,
            is_fraudulent: tx.status === 'Fraud' ? 1 : 0,
            risk_level: tx.riskLevel,
            model_scores: tx.modelScores || {},
            explanation: tx.explanation || {}
        };

        // Send a copy of the scored transaction to PHP for storage
        const response = await fetch(PHP_BACKEND_API, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!response.ok) {
            const text = await response.text();
            console.warn('PHP storage failed:', response.status, text);
            return null;
        }
        return await response.json();
    } catch (err) {
        console.warn('PHP storage call failed:', err);
        return null;
    }
}


function recordAlert(tx) {
    const alerts = loadAlerts();
    alerts.unshift({
        id: tx.id,
        time: tx.time,
        amount: tx.amount,
        merchant: tx.merchant,
        type: tx.type,
        note: tx.note,
        riskScore: tx.riskScore,
        status: tx.status,
        reason: buildRiskReason(tx),
        timestamp: tx.timestamp
    });
    saveAlerts(alerts);
}

function pushTransaction(tx) {
    const txList = loadTransactions();
    txList.unshift(tx);
    saveTransactions(txList);
    if (tx.status === 'Fraud') {
        recordAlert(tx);
    }
    return txList;
}

function getLatestAlertCounts() {
    const alerts = loadAlerts();
    const fraud = alerts.filter(a => a.status === 'Fraud').length;
    return {
        total: alerts.length,
        fraud
    };
}

function getLatestRisk(tx) {
    const explain = buildXAIExplainability(tx);
    const high = explain.reduce((sum, item) => sum + item.value, 0) / explain.length;
    return Math.round(high);
}

function getFriendlyModelLabel(settings) {
    return `${settings.ensembleMode} + ${settings.fraudSensitivity} Sensitivity`;
}
