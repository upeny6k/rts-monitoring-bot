"""India Post IT 2.0 tracking automation for RTS Monitoring project."""

from .article_utils import normalize_article_no, is_valid_article_no

__all__ = ["normalize_article_no", "is_valid_article_no"]

# Excel: Col C = Destination SO; Col I = "IT 2.0 remark"
# Auth: TOTP (APT app), not SMS OTP — see Sample Video/IT20_RUNBOOK.md
