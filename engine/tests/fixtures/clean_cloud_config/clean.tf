provider "aws" {
  region = "us-east-1"
}

resource "aws_s3_bucket" "clean" {
  bucket = "acme-clean-bucket"
  acl    = "private"
}

resource "aws_s3_bucket_public_access_block" "clean" {
  bucket = aws_s3_bucket.clean.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_security_group" "clean_sg" {
  name = "clean-sg"
  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "clean_db" {
  allocated_storage = 20
  engine            = "postgres"
  storage_encrypted = true
}
