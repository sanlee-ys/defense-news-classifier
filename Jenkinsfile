// Jenkinsfile — declarative CI pipeline for defense-news-classifier.
//
// Pipeline-as-code expressing this repo's CI as a Jenkins pipeline, mirroring the
// GitHub Actions workflows: .github/workflows/tests.yml in full, and the free
// offline-gate job of .github/workflows/evals.yml (never its paid live-capability-eval
// job -- see the Eval gate stage below). GitHub Actions is the live gate for this repo;
// this file is the same pipeline written for a Jenkins controller (e.g. an enterprise
// one). No controller runs it here, so it carries no status check.
//
// Agent requirements: a node with uv-capable Python 3.11+. `agent any` keeps this
// portable to read; a real setup would pin a labeled node or a uv-baked image.

pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 20, unit: 'MINUTES')
        // Mirror the Actions concurrency guard: a newer commit on the same branch
        // supersedes an in-flight build.
        disableConcurrentBuilds(abortPrevious: true)
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        // Keep uv's cache and the installed binary inside the workspace / on PATH so
        // each fresh `sh` shell can find them.
        UV_CACHE_DIR = "${WORKSPACE}/.uv-cache"
        PATH = "${env.HOME}/.local/bin:${env.PATH}"
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Setup (uv sync)') {
            steps {
                // Real agents would bake uv into the image; install here to stay
                // self-contained. --frozen fails if uv.lock drifts from pyproject.
                sh '''
                    command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
                    uv --version
                    uv sync --frozen
                '''
            }
        }

        // Lint, format, and type checks are independent — run them in parallel so a
        // slow check doesn't serialize the others (and all failures surface in one run).
        stage('Quality') {
            parallel {
                stage('Lint (ruff)') {
                    steps { sh 'uv run ruff check .' }
                }
                stage('Format (black)') {
                    steps { sh 'uv run black --check .' }
                }
                stage('Types (mypy)') {
                    steps { sh 'uv run mypy src' }
                }
            }
        }

        stage('Unit tests') {
            steps {
                // Offline unit suite. Coverage gate matches the Actions gate
                // (--cov-fail-under=66).
                sh '''
                    uv run pytest \
                        --cov=src --cov-report=xml --cov-report=term-missing \
                        --cov-fail-under=66 \
                        --junitxml=reports/junit-unit.xml
                '''
            }
            post {
                always { junit 'reports/junit-unit.xml' }
            }
        }

        stage('Eval gate (offline)') {
            // Parity-only: mirrors .github/workflows/evals.yml's offline-gate job (grades
            // the prediction CSVs already committed in evals/ against
            // evals/thresholds.toml -- no ANTHROPIC_API_KEY, no network call). No Jenkins
            // controller runs this file, so it carries no status check here, same as the
            // rest of this pipeline, and it deliberately mirrors ONLY the free offline
            // gate -- never evals.yml's live-capability-eval job, which needs a secret and
            // real model calls. GitHub Actions is the live gate for both; see
            // decisions/007-evals-as-ci-gate.md.
            steps {
                sh 'uv run python src/eval_gate.py'
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: 'coverage.xml', allowEmptyArchive: true
            // With the Coverage plugin installed, publish the trend too:
            //   recordCoverage(tools: [[parser: 'COBERTURA', pattern: 'coverage.xml']])
        }
        success {
            echo 'Green: lint + format + types + unit (coverage gate) + offline eval gate.'
        }
        failure {
            echo 'Pipeline failed — open the failing stage for the log.'
        }
    }
}
