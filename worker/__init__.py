WORKER_LAMBDA_EXCLUDE = [
    "!worker",
    "!worker/**",
    "worker/layer",
    "worker/tests",
    "worker/poetry.lock",
    "worker/pyproject.toml",
    "worker/README.md",
    "worker/template.yml",
    "worker/requirements.txt",
    "worker/simple_event.json",
    "worker/worker_cdk_stack.py",
]
