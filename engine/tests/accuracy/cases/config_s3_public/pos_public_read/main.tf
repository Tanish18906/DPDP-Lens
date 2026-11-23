resource "aws_s3_bucket" "student_records" {
  bucket = "acme-student-records"
  acl    = "public-read"
}
