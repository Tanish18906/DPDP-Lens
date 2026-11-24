"""Unit tests for Block 14: Cloud configuration checks in config_scan."""
import tempfile
from pathlib import Path

import pytest

from dpdp_lens.scanners import config_scan


@pytest.fixture
def tmp_app(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    return app


def test_clean_cloud_config_control_fixture():
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "clean_cloud_config"
    findings = config_scan.scan(str(fixture_dir))
    assert findings == [], f"Expected 0 findings on clean control fixture, got: {findings}"


def test_s3_public_bucket_acl_detected(tmp_app):
    (tmp_app / "main.tf").write_text("""
resource "aws_s3_bucket" "b" {
  bucket = "acme-public"
  acl    = "public-read"
}
""")
    findings = config_scan.scan(str(tmp_app))
    s3_findings = [f for f in findings if f.check == "config_s3_public"]
    assert len(s3_findings) == 1
    f = s3_findings[0]
    assert f.severity == "high"
    assert f.layer == "config"
    assert "public-read" in f.evidence.masked_sample
    assert f.evidence.location.file == "main.tf"
    assert f.fix.available is False


def test_s3_public_access_block_disabled_detected(tmp_app):
    (tmp_app / "s3.tf").write_text("""
resource "aws_s3_bucket_public_access_block" "pab" {
  bucket = "acme-bucket"
  block_public_acls = false
}
""")
    findings = config_scan.scan(str(tmp_app))
    s3_findings = [f for f in findings if f.check == "config_s3_public"]
    assert len(s3_findings) == 1
    assert "block_public_acls = false" in s3_findings[0].evidence.masked_sample


def test_s3_bucket_hard_negatives(tmp_app):
    (tmp_app / "main.tf").write_text("""
# acl = "public-read"
// block_public_acls = false
resource "aws_s3_bucket" "b1" {
  bucket = "acme-private"
  acl    = "private"
}
resource "aws_s3_bucket" "b2" {
  bucket = "acme-var"
  acl    = var.s3_acl
}
resource "aws_s3_bucket_public_access_block" "pab" {
  bucket = "acme-bucket"
  block_public_acls = true
}
""")
    findings = config_scan.scan(str(tmp_app))
    assert not any(f.check == "config_s3_public" for f in findings)


def test_security_group_ingress_database_ssh_anywhere_detected(tmp_app):
    (tmp_app / "sg.tf").write_text("""
resource "aws_security_group" "db_sg" {
  name = "db"
  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
""")
    findings = config_scan.scan(str(tmp_app))
    sg_findings = [f for f in findings if f.check == "config_security_group_ingress_anywhere"]
    assert len(sg_findings) == 1
    assert "5432" in sg_findings[0].severity_reason


def test_security_group_ingress_hard_negatives(tmp_app):
    (tmp_app / "sg.tf").write_text("""
# ingress on 22 to 0.0.0.0/0 commented out
# ingress {
#   from_port = 22
#   to_port = 22
#   cidr_blocks = ["0.0.0.0/0"]
# }
resource "aws_security_group" "private_db" {
  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }
}
resource "aws_security_group" "public_web" {
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
""")
    findings = config_scan.scan(str(tmp_app))
    assert not any(f.check == "config_security_group_ingress_anywhere" for f in findings)


def test_storage_unencrypted_detected(tmp_app):
    (tmp_app / "db.tf").write_text("""
resource "aws_db_instance" "db" {
  engine            = "postgres"
  storage_encrypted = false
}
""")
    findings = config_scan.scan(str(tmp_app))
    enc_findings = [f for f in findings if f.check == "config_storage_unencrypted"]
    assert len(enc_findings) == 1
    assert "storage_encrypted = false" in enc_findings[0].evidence.masked_sample


def test_storage_unencrypted_hard_negatives(tmp_app):
    (tmp_app / "db.tf").write_text("""
# storage_encrypted = false
resource "aws_db_instance" "db1" {
  storage_encrypted = true
}
resource "aws_db_instance" "db2" {
  storage_encrypted = var.encrypted
}
""")
    findings = config_scan.scan(str(tmp_app))
    assert not any(f.check == "config_storage_unencrypted" for f in findings)


def test_tf_hardcoded_secret_detected(tmp_app):
    (tmp_app / "provider.tf").write_text("""
provider "aws" {
  region     = "us-east-1"
  access_key = "AKIAIOSFODNN7EXAMPLE"
  secret_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
}
""")
    findings = config_scan.scan(str(tmp_app))
    tf_secrets = [f for f in findings if f.check == "config_tf_hardcoded_secret"]
    assert len(tf_secrets) == 1
    assert "AK***" in tf_secrets[0].evidence.masked_sample or "wJ***" in tf_secrets[0].evidence.masked_sample


def test_tf_hardcoded_secret_hard_negatives(tmp_app):
    (tmp_app / "provider.tf").write_text("""
# access_key = "AKIAIOSFODNN7EXAMPLE"
provider "aws" {
  region     = "us-east-1"
  access_key = var.aws_access_key
  secret_key = var.aws_secret_key
}
""")
    findings = config_scan.scan(str(tmp_app))
    assert not any(f.check == "config_tf_hardcoded_secret" for f in findings)


def test_k8s_privileged_detected(tmp_app):
    (tmp_app / "deploy.yaml").write_text("""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: workload
spec:
  template:
    spec:
      containers:
        - name: app
          image: app:latest
          securityContext:
            privileged: true
""")
    findings = config_scan.scan(str(tmp_app))
    priv = [f for f in findings if f.check == "config_k8s_privileged"]
    assert len(priv) == 1
    assert "privileged: true" in priv[0].evidence.masked_sample


def test_k8s_privileged_root_detected(tmp_app):
    (tmp_app / "pod.yaml").write_text("""
apiVersion: v1
kind: Pod
metadata:
  name: root-pod
spec:
  securityContext:
    runAsUser: 0
  containers:
    - name: worker
      image: worker:latest
""")
    findings = config_scan.scan(str(tmp_app))
    priv = [f for f in findings if f.check == "config_k8s_privileged"]
    assert len(priv) == 1
    assert "runAsUser: 0" in priv[0].evidence.masked_sample


def test_k8s_privileged_hard_negatives(tmp_app):
    (tmp_app / "deploy.yaml").write_text("""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: secure-app
spec:
  template:
    spec:
      containers:
        - name: app
          image: app:latest
          securityContext:
            privileged: false
            runAsUser: 10001
            allowPrivilegeEscalation: false
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: info
data:
  privileged: "true"
""")
    findings = config_scan.scan(str(tmp_app))
    assert not any(f.check == "config_k8s_privileged" for f in findings)


def test_k8s_host_network_detected(tmp_app):
    (tmp_app / "deploy.yaml").write_text("""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: host-app
spec:
  template:
    spec:
      hostNetwork: true
      containers:
        - name: app
          image: nginx:latest
""")
    findings = config_scan.scan(str(tmp_app))
    hn = [f for f in findings if f.check == "config_k8s_host_network"]
    assert len(hn) == 1
    assert "host network" in hn[0].title.lower()
    assert "hostNetwork: true" in hn[0].evidence.masked_sample


def test_k8s_host_network_hard_negatives(tmp_app):
    (tmp_app / "deploy.yaml").write_text("""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: normal-app
spec:
  template:
    spec:
      hostNetwork: false
      containers:
        - name: app
          image: nginx:latest
""")
    findings = config_scan.scan(str(tmp_app))
    assert not any(f.check == "config_k8s_host_network" for f in findings)


def test_k8s_secret_in_env_detected(tmp_app):
    (tmp_app / "deploy.yaml").write_text("""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          image: api:latest
          env:
            - name: API_SECRET_KEY
              value: "superSecretToken1234"
""")
    findings = config_scan.scan(str(tmp_app))
    env_sec = [f for f in findings if f.check == "config_k8s_secret_in_env"]
    assert len(env_sec) == 1
    assert "API_SECRET_KEY=su***" in env_sec[0].evidence.masked_sample


def test_k8s_secret_in_env_hard_negatives(tmp_app):
    (tmp_app / "deploy.yaml").write_text("""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          image: api:latest
          env:
            - name: API_SECRET_KEY
              valueFrom:
                secretKeyRef:
                  name: api-secret
                  key: key
            - name: PORT
              value: "8000"
            - name: JWT_SECRET
              value: "change-me"
            - name: DB_PASSWORD
              value: "$(SECRET_VAR)"
""")
    findings = config_scan.scan(str(tmp_app))
    assert not any(f.check == "config_k8s_secret_in_env" for f in findings)


def test_invalid_terraform_and_yaml_does_not_crash(tmp_app):
    (tmp_app / "broken.tf").write_text("""
resource "broken" {
  acl = 
  unterminated string "hello
""")
    (tmp_app / "broken.yaml").write_text("""
kind: Deployment
spec:
  template: [unbalanced
  : - bad yaml
""")
    # Scanner must run without throwing an unhandled exception
    findings = config_scan.scan(str(tmp_app))
    assert isinstance(findings, list)
