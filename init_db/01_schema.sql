-- 1. Tabella Obbligatoria: web_resources
CREATE TABLE web_resources (
    url VARCHAR(768) PRIMARY KEY,   
    domain VARCHAR(255),
    title VARCHAR(2048),
    html_text LONGTEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2. Tabella Obbligatoria: gold_standard
CREATE TABLE gold_standard (
    url VARCHAR(768) PRIMARY KEY,
    gold_text LONGTEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (url) REFERENCES web_resources(url) ON DELETE CASCADE
);

-- 3. Tabella: parsed_results (utile per tracking e aggregazioni)
CREATE TABLE parsed_results (
    id INT AUTO_INCREMENT PRIMARY KEY,
    url VARCHAR(768) UNIQUE,
    parsed_text LONGTEXT,
    parser_version VARCHAR(50),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (url) REFERENCES web_resources(url) ON DELETE CASCADE
);

-- 4. Tabella: evaluation_results (cache per /db_stats)
CREATE TABLE evaluation_results (
    id INT AUTO_INCREMENT PRIMARY KEY,
    url VARCHAR(768),
    precision_score FLOAT,
    recall_score FLOAT,
    f1_score FLOAT,
    extra_metrics JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (url) REFERENCES web_resources(url) ON DELETE CASCADE
);

-- 5. Tabella: llm_judge_results (serve a /db_stats e /evaluate_judge)
CREATE TABLE llm_judge_results (
    id INT AUTO_INCREMENT PRIMARY KEY,
    url VARCHAR(768),
    model_name VARCHAR(100),
    judge_score INT,
    judge_feedback TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (url) REFERENCES web_resources(url) ON DELETE CASCADE
);