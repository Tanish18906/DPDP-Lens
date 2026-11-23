resource "aws_s3_bucket_public_access_block" "bad" {
  bucket = "acme-data"
  block_public_acls = false
}
