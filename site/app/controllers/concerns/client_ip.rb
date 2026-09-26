# The uploader's IP address, for the per-network upload limit. Behind
# Railway's edge, request.remote_ip is the edge's own address, so production
# reads the X-Real-IP header Railway's edge sets instead (CLIENT_IP_HEADER
# overrides the header; empty means remote_ip).
#
# X-Real-IP rather than X-Forwarded-For: Railway's edge overwrites a
# client-sent X-Real-IP (fixed in August 2024; checked against
# omarchy-m-testing.org in September 2026: uploads each claiming a different
# X-Real-IP still shared one limit), while Railway staff disagree on whether
# it strips or appends to a client-sent X-Forwarded-For. With Railway's CDN
# enabled X-Real-IP becomes the CDN's address, so keep the CDN off for /api.
module ClientIp
  def self.header
    ENV.fetch("CLIENT_IP_HEADER") { Rails.env.production? ? "X-Real-IP" : "" }.presence
  end

  private

  def client_ip
    (ClientIp.header && request.headers[ClientIp.header].to_s.strip.presence) || request.remote_ip
  end
end
