resource "aws_s3_bucket" "var_acl" {
  bucket = "acme-data"
  acl    = var.bucket_acl
}
