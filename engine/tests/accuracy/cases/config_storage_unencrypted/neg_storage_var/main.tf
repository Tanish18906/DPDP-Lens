resource "aws_db_instance" "db" {
  storage_encrypted = var.enable_encryption
}
