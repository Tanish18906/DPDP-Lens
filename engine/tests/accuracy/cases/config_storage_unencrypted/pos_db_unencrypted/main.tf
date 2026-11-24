resource "aws_db_instance" "db" {
  allocated_storage = 20
  engine            = "postgres"
  storage_encrypted = false
}
