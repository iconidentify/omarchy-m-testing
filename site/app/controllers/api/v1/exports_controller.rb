module Api
  module V1
    # The rest of the public data, CC0: every check result as CSV, and the
    # compatibility matrix and the benchmark comparison as JSON.
    class ExportsController < ActionController::API
      def checks
        send_data DataExport.checks_csv, type: "text/csv; charset=utf-8", filename: "omarchy-m-testing-checks.csv"
      end

      def matrix
        render json: { license: DataExport::LICENSE, generated_at: Time.current.utc.iso8601, **CompatibilityMatrix.visible.as_json }
      end

      def benchmarks
        render json: { license: DataExport::LICENSE, generated_at: Time.current.utc.iso8601, **BenchmarkScores.visible.as_json }
      end
    end
  end
end
