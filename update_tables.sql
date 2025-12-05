-- 1. Agregar columnas a tabla Students
ALTER TABLE students ADD COLUMN rfid_code VARCHAR(50) UNIQUE DEFAULT NULL;
ALTER TABLE students ADD COLUMN has_lunch BOOLEAN DEFAULT FALSE;
ALTER TABLE students ADD COLUMN lunch_type ENUM('Normal', 'Especial', 'Ninguno') DEFAULT 'Ninguno';

-- 2. Crear tabla Employees
CREATE TABLE employees (
    id INT AUTO_INCREMENT PRIMARY KEY,
    doc_id VARCHAR(20) NOT NULL UNIQUE,
    full_name VARCHAR(100) NOT NULL,
    position VARCHAR(50),
    photo_path VARCHAR(255),
    rfid_code VARCHAR(50) UNIQUE DEFAULT NULL,
    has_lunch BOOLEAN DEFAULT FALSE,
    lunch_type ENUM('Normal', 'Especial', 'Ninguno') DEFAULT 'Normal',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 3. Crear tabla Lunch Logs
CREATE TABLE lunch_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT DEFAULT NULL,
    employee_id INT DEFAULT NULL,
    operator_id INT NOT NULL,
    timestamp DATETIME NOT NULL,
    delivered_type ENUM('Normal', 'Especial', 'Ninguno') NOT NULL,
    FOREIGN KEY (student_id) REFERENCES students(id),
    FOREIGN KEY (employee_id) REFERENCES employees(id),
    FOREIGN KEY (operator_id) REFERENCES users(id)
);

