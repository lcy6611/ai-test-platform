pipeline {
    agent any
    environment {
        PYTHONUNBUFFERED = 1
        DEEPSEEK_API_KEY = credentials('DEEPSEEK_API_KEY') // Jenkins凭据ID需一致
    }
    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }
        stage('Install Dependencies') {
            steps {
                bat 'pip install -r requirements.txt'
                bat 'playwright install'
                bat 'pip install allure-pytest'
            }
        }
        stage('Page Snapshot') {
            steps {
                bat 'python page_snapshot_collector.py'
            }
        }
        stage('Generate Test Cases') {
            steps {
                bat 'python testcases_generator_by_snapshot.py'
            }
        }
        stage('Generate Scripts') {
            steps {
                bat 'python script_generator.py'
            }
        }
        stage('Run Tests') {
            steps {
                bat 'python run_tests.py'
            }
        }
        stage('Auto Heal') {
            steps {
                bat 'python auto_heal.py'
            }
        }
        stage('Re-Run Healed Tests') {
            steps {
                bat 'pytest playwright_test_*.py.healed --alluredir=allure-results || exit 0'
            }
        }
        // 如未安装Allure插件，先注释掉此步骤
        // stage('Allure Report') {
        //     steps {
        //         allure includeProperties: false, jdk: '', results: [[path: 'allure-results']]
        //     }
        // }
    }
    post {
        always {
            archiveArtifacts artifacts: '**/*.healed, **/*.bak, allure-results/**', allowEmptyArchive: true
        }
    }
}