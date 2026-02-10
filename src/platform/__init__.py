"""VCS and PR integration."""
from src.platform.git_ops import clone_repo, checkout_branch, stage_and_commit, push_branch, generate_branch_name, get_repo_name
from src.platform.pr_platform import PRPlatform, GitHubPR, BitbucketPR, get_pr_platform
from src.platform.reference_pr import parse_pr_url, fetch_reference_pr, get_reference_pr_context
