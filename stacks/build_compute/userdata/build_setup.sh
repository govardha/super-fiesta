#!/bin/bash
# UserData for build compute instances (x86 and ARM).
# Shared by both X86BuildStack and ArmBuildStack.
# Edit this file to add packages/tools — both stacks pick it up.
set -euo pipefail

dnf install -y docker docker-compose-plugin git tmux make
systemctl enable --now docker
usermod -aG docker ec2-user

# docker buildx — dnf package is broken on AL2023, install from GitHub
BUILDX_VERSION="v0.17.1"
ARCH=$(uname -m)
if [[ "${ARCH}" == "aarch64" ]]; then
  BUILDX_ARCH="arm64"
else
  BUILDX_ARCH="amd64"
fi
mkdir -p /usr/libexec/docker/cli-plugins
curl -SL "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-${BUILDX_ARCH}" \
  -o /usr/libexec/docker/cli-plugins/docker-buildx
chmod +x /usr/libexec/docker/cli-plugins/docker-buildx

# lazygit
LAZYGIT_VERSION=$(curl -s https://api.github.com/repos/jesseduffield/lazygit/releases/latest | grep '"tag_name"' | sed 's/.*"v\([^"]*\)".*/\1/')
ARCH=$(uname -m)
if [[ "${ARCH}" == "aarch64" ]]; then
  LAZYGIT_ARCH="arm64"
else
  LAZYGIT_ARCH="x86_64"
fi
curl -Lo /tmp/lazygit.tar.gz "https://github.com/jesseduffield/lazygit/releases/download/v${LAZYGIT_VERSION}/lazygit_${LAZYGIT_VERSION}_Linux_${LAZYGIT_ARCH}.tar.gz"
tar -xzf /tmp/lazygit.tar.gz -C /usr/local/bin lazygit
rm -f /tmp/lazygit.tar.gz

# gh CLI — not in AL2023 default repos
dnf install -y dnf-plugins-core
dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo
dnf install -y gh

# Authenticate gh and clone build repo
aws ssm get-parameter --name /notify/gh-pat --with-decryption --query 'Parameter.Value' --output text > /tmp/gh_token
runuser -l ec2-user -c '
  gh auth login --with-token < /tmp/gh_token 2>/dev/null || true
  gh auth setup-git
  git clone https://github.com/super-octo-broccoli/py-build.git /home/ec2-user/py-build
'
rm -f /tmp/gh_token
