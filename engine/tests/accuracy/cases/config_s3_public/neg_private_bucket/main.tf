resource "aws_s3_bucket" "secure" {
  bucket = "acme-secure"
  acl    = "private"
}
