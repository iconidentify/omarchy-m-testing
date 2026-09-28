module Api
  module V1
    # POST /api/v1/tester_requests: omarchy-m-test --status and --sign-out
    # (and a run asking, once, whether its Mac is signed in before offering
    # the sign-in). The body is signed by the machine's key under
    # MachineSignature::TESTER_NAMESPACE, like a sign-in:
    #
    #   { "request_version": 1, "request": "status", "requested_at": <unix seconds>, "signature": {...} }
    #   { "request_version": 1, "request": "sign-out", "sign_in": "<id>", "requested_at": ..., "signature": {...} }
    #
    # A request dated more than MAX_AGE from the site's clock is refused. A
    # status names the sign-in (TesterBinding#sign_in_id) and a sign-out must
    # name the one it ends, so a copy of a sign-out can't unbind the machine
    # after it signs in again. Both answer where the machine stands afterwards:
    #
    #   { "signed_in": true, "login": "handle", "tester": true, "sign_in": "<id>" } or { "signed_in": false }
    #
    # and a sign-out also says which handle it unbound ("signed_out", or null
    # when the machine wasn't bound). Runs already uploaded keep the handle
    # they were uploaded under.
    class TesterRequestsController < ActionController::API
      include ClientIp

      VERSION = 1
      MAX_AGE = 1.day
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
          return refuse("The request is dated more than a day from the site's clock. Check this Mac's date and time, then try again.")
        end

        binding = TesterBinding.find_by(machine_id: signature.machine_id)
        if payload["request"] == "sign-out"
          return render(json: { signed_in: false, signed_out: nil }) unless binding
          # Only the sign-in the request names, and only if it's still that one (a sign-in racing this unbinds nothing).
          unless binding.sign_in_id == payload["sign_in"] && TesterBinding.where(id: binding.id, updated_at: binding.updated_at).delete_all == 1
            return refuse("This Mac signed in again after this sign-out was made, so it was refused. Run omarchy-m-test --sign-out again.", :conflict)
          end
          render json: { signed_in: false, signed_out: binding.github_login }
        elsif binding
          render json: { signed_in: true, login: binding.github_login, tester: binding.tester?, sign_in: binding.sign_in_id }
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
        return false unless payload.is_a?(Hash) && payload["request_version"] == VERSION && payload["requested_at"].is_a?(Integer)

        case payload["request"]
        when "status" then payload.keys.sort == %w[request request_version requested_at signature]
        when "sign-out" then payload.keys.sort == %w[request request_version requested_at sign_in signature] && payload["sign_in"].to_s.match?(/\A\d{1,20}\z/)
        else false
        end
      end

      def refuse(error, status = :unprocessable_content) = render(json: { error: }, status:)
    end
  end
end
