"""Language Server Protocol support.

One server, so a contract gets diagnostics in VS Code, Neovim, JetBrains, Helix
and Zed without five plugins that each reimplement the same lint.
"""

from apiverity.lsp.server import LanguageServer, main, serve

__all__ = ["LanguageServer", "main", "serve"]
