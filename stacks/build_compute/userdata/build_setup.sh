#!/bin/bash
# UserData for build compute instances (x86 and ARM).
# Shared by both X86BuildStack and ArmBuildStack.
# Edit this file to add packages/tools — both stacks pick it up.
set -euo pipefail

dnf install -y docker git
systemctl enable --now docker
usermod -aG docker ec2-user

# gh CLI — not in AL2023 default repos
dnf install -y dnf-plugins-core
dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo
dnf install -y gh
