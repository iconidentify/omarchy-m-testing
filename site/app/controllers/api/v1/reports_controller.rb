module Api
  module V1
    class ReportsController < ActionController::API
      # Evidence is capped at 64 KiB per report; this leaves room for everything else.
      MAX_BODY_BYTES = 256.kilobytes

      def create
        length = request.content_length
        return render(json: { error: "Send the report with a Content-Length." }, status: :length_required) if length.nil?
        return render(json: { error: "The report is larger than #{MAX_BODY_BYTES / 1.kilobyte} KiB." }, status: :content_too_large) if length > MAX_BODY_BYTES

        payload = JSON.parse(request.raw_post)
      rescue JSON::ParserError
        render json: { error: "The report is not valid JSON." }, status: :bad_request
      else
        problems = ReportSchema.errors(payload)
        unknown = problems.any? ? [] : Catalogue.unknown_check_ids(payload)
        if problems.any?
          render json: { error: "The report does not match report schema v#{ReportSchema::VERSION}.", details: problems },
                 status: :unprocessable_content
        elsif unknown.any?
          render json: { error: "The report has checks this site doesn't know (feature catalogue v#{Catalogue.version}). Update omarchy-m-test and run it again.",
                         details: unknown.map { |id| "unknown check id #{id}" } },
                 status: :unprocessable_content
        else
          report = Report.create!(body: payload, schema_version: payload.fetch("schema_version"))
          render json: {
            id: report.public_id,
            report_url: report_url(report),
            deletion_url: deletion_report_url(report, token: report.deletion_token)
          }, status: :created
        end
      end
    end
  end
end
