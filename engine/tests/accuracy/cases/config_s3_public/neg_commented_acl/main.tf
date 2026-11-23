resource "aws_s3_bucket" "commented" {
  bucket = "acme-data"
  # acl = "public-read"
}
