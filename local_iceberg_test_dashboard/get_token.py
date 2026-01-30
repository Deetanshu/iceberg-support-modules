#!/usr/bin/env python3
"""
Quick script to exchange Google OAuth code for JWT token.

Usage:
    python get_token.py "https://botbro.ronykax.xyz/api/auth/callback/google?code=..."
"""

import asyncio
import sys
from urllib.parse import urlparse, parse_qs
import httpx


async def exchange_code(auth_code: str) -> None:
    """Exchange authorization code for JWT token."""
    
    print(f"Authorization code: {auth_code[:50]}...")
    print("\nExchanging code for JWT token...")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                "https://api.botbro.trade/v1/auth/google/exchange",
                json={"authorization_code": auth_code},
                headers={"Content-Type": "application/json"},
            )
            
            result = response.json()
            
            if result.get("ok"):
                token = result["data"]["token"]
                user = result["data"]["user"]
                
                print("\n✅ SUCCESS!")
                print(f"\nUser: {user.get('email')} ({user.get('role')})")
                print(f"\nJWT Token:")
                print(token)
                print(f"\n\nTo use this token, add it to local_iceberg_test_dashboard/.env:")
                print(f"ICEBERG_JWT_TOKEN={token}")
                
            else:
                print("\n❌ FAILED!")
                print(f"Error: {result.get('error', {}).get('message')}")
                print(f"Details: {result.get('error', {}).get('details')}")
                
        except Exception as e:
            print(f"\n❌ ERROR: {e}")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python get_token.py <callback_url_or_code>")
        print("\nExample:")
        print('  python get_token.py "https://botbro.ronykax.xyz/api/auth/callback/google?code=..."')
        print('  python get_token.py "4/0ASc3gC2Gu0CbxBSCdW1jo62cQ34SXV-..."')
        sys.exit(1)
    
    input_str = sys.argv[1]
    
    # Check if it's a URL or just a code
    if input_str.startswith("http"):
        parsed = urlparse(input_str)
        params = parse_qs(parsed.query)
        auth_code = params.get('code', [''])[0]
        if not auth_code:
            print("ERROR: No 'code' parameter found in URL")
            sys.exit(1)
    else:
        auth_code = input_str
    
    asyncio.run(exchange_code(auth_code))


if __name__ == "__main__":
    main()
