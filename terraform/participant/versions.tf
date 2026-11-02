terraform {
  required_version = ">= 1.9"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.67" }
    random = { source = "hashicorp/random", version = "~> 3.7" }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags { tags = local.tags }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
