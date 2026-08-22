"""Contract coverage measurement.

Measures which parts of the *contract* were exercised by test runs,
workflows or recorded traffic — reported separately from application code
coverage.
"""

from apiverity.coverage.coverage import CoverageReport, measure_coverage

__all__ = ["CoverageReport", "measure_coverage"]