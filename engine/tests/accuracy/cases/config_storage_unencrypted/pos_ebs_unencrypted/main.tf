resource "aws_ebs_volume" "vol" {
  size      = 40
  encrypted = false
}
