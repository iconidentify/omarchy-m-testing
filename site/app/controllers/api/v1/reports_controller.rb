module Api
  module V1
    class ReportsController < ActionController::API
      include ClientIp

      # Evidence is capped at 64 KiB per report; this leaves room for everything else.
      MAX_BODY_BYTES = 256.kilobytes
      UPLOADS_PER_HOUR = ENV.fetch("UPLOADS_PER_HOUR", 30).to_i
      # In-process, so limits reset on deploy; the site runs one web process.
      RATE_LIMITS = ActiveSupport::Cache::MemoryStore.new

      rate_limit to: UPLOADS_PER_HOUR, within: 1.hour, by: -> { client_ip }, only: :create, store: RATE_LIMITS,
                 with: -> { render json: { error: "Too many uploads from your network: at most #{UPLOADS_PER_HOUR} an hour. Try again later; the report is saved on your Mac." }, status: :too_many_requests }

      # Every visible report as uploaded (JSON), or one row per report (CSV). CC0.
      def index
        url_for = ->(report) { report_url(report) }
        if request.format.csv?
          send_data DataExport.reports_csv(url_for), type: "text/csv; charset=utf-8", filename: "omarchy-m-testing-reports.csv"
        else
          render json: DataExport.json(url_for)
        end
      end

      def create
        length = request.content_length
        return render(json: { error: "Send the report with a Content-Length." }, status: :length_required) if length.nil?
        return render(json: { error: "The report is larger than #{MAX_BODY_BYTES / 1.kilobyte} KiB." }, status: :content_too_large) if length > MAX_BODY_BYTES

        payload = JSON.parse(request.raw_post)
      rescue JSON::ParserError
        render json: { error: "The report is not valid JSON." }, status: :bad_request
      else
        if (outdated = outdated_schema_error(payload))
          render json: outdated, status: :unprocessable_content
        elsif (problems = ReportSchema.errors(payload)).any?
          render json: { error: "The report does not match report schema v#{ReportSchema::VERSION}.", details: problems },
                 status: :unprocessable_content
        elsif (unknown = Catalogue.unknown_check_ids(payload)).any?
          render json: { error: "The report has checks this site doesn't know (feature catalogue v#{Catalogue.version}). #{upgrade}",
                         details: unknown.map { |id| "unknown check id #{id}" } },
                 status: :unprocessable_content
        elsif (problems = ReportEvidence.errors(payload)).any?
          render json: { error: "The report's evidence must be text and at most 64 KiB.", details: problems },
                 status: :unprocessable_content
        else
          report = Report.create!(body: payload, schema_version: payload.fetch("schema_version"), machine_id: Report.machine_id_for_ip(client_ip))
          render json: {
            id: report.public_id,
            report_url: report_url(report),
            deletion_url: deletion_report_url(report, token: report.deletion_token)
          }, status: :created
        end
      end

      private

      def upgrade = "Update omarchy-m-test (curl -fsSL #{install_url} | bash) and run it again."

      def outdated_schema_error(payload)
        version = payload["schema_version"] if payload.is_a?(Hash)
        return unless version.is_a?(Integer) && version < ReportSchema::VERSION

        { error: "This report uses report schema v#{version}, which is outdated: the site accepts v#{ReportSchema::VERSION}. #{upgrade}",
          details: [ "schema_version #{version} is older than #{ReportSchema::VERSION}" ] }
      end
    end
  end
end
