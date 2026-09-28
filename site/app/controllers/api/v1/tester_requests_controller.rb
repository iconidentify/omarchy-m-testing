module Api
  module V1
    # POST /api/v1/tester_requests: omarchy-m-test --status and --sign-out
    # (and a run asking, once, whether its Mac is signed in before offering
    # the sign-in). The body is signed by the machine's key under
    # MachineSignature::TESTER_NAMESPACE, like a sign-in:
    #
    #   { "request_version": 1, "request": "status" | "sign-out", "requested_at": <unix seconds>, "signature": {...} }
    #
    # A request dated more than MAX_AGE from now is refused, so a copy of a
    # sign-out can't unbind the machine later. Both answer where the machine
    # stands afterwards:
    #
    #   { "signed_in": true, "login": "handle", "tester": true } or { "signed_in": false }
    #
    # and a sign-out also says which handle it unbound ("signed_out", or null
    # when the machine wasn't bound). Runs already uploaded keep the handle
    # they were uploaded under.
    class TesterRequestsController < ActionController::API
      include ClientIp

      VERSION = 1
      REQUESTS = %w[status sign-out].freeze
      MAX_AGE = 1.hour
      MAX_BODY_BYTES = 8.kilobytes
      PER_HOUR = ENV.fetch("TESTER_REQUESTS_PER_HOUR", 60).to_i

      rate_limit to: PER_HOUR, within: 1.hour, by: -> { client_ip }, store: ReportsController::RATE_LIMITS,
                 with: -> { render json: { error: "Too many requests from your network: at most #{PER_HOUR} an hour. Try again later." }, status: :too_many_requests }

      def create
        return refuse("The request is larger than #{MAX_BODY_BYTES / 1.kilobyte} KiB.", :content_too_large) if request.content_length.to_i > MAX_BODY_BYTES

        payload = JSON.parse(request.raw_post)
        return refuse("The request isn't what omarchy-m-test sends. Update omarchy-m-test and try again.") unless well_formed?(payload)

        signature = MachineSignature.verify!(payload, namespace: MachineSignature::TESTER_NAMESPACE)
        unless (Time.current.to_i - payload["requested_at"]).abs <= MAX_AGE
          return refuse("The request is dated more than an hour from the site's clock. Check this Mac's date and time, then try again.")
        end

        binding = TesterBinding.find_by(machine_id: signature.machine_id)
        if payload["request"] == "sign-out"
          binding&.destroy!
          render json: { signed_in: false, signed_out: binding&.github_login }
        elsif binding
          render json: { signed_in: true, login: binding.github_login, tester: binding.tester? }
        else
          render json: { signed_in: false }
        end
      rescue JSON::ParserError
        refuse("The request is not valid JSON.", :bad_request)
      rescue MachineSignature::Invalid => invalid
        refuse("The request's signature is not valid, so it was refused (#{invalid.message}).")
      end

      private

      def well_formed?(payload)
        payload.is_a?(Hash) && payload.keys.sort == %w[request request_version requested_at signature] &&
          payload["request_version"] == VERSION && REQUESTS.include?(payload["request"]) && payload["requested_at"].is_a?(Integer)
      end

      def refuse(error, status = :unprocessable_content) = render(json: { error: }, status:)
    end
  end
end
