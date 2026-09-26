# The uploader's IP address. Behind Railway's edge, request.remote_ip is the
# edge's own address, so production reads the X-Real-IP header Railway's proxy
# sets instead (CLIENT_IP_HEADER overrides the header; empty means remote_ip).
module ClientIp
  def self.header
    ENV.fetch("CLIENT_IP_HEADER") { Rails.env.production? ? "X-Real-IP" : "" }.presence
  end

  private

  def client_ip
    (ClientIp.header && request.headers[ClientIp.header].to_s.strip.presence) || request.remote_ip
  end
end
