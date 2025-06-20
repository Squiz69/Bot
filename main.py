import discord
from discord.ext import commands, tasks
from discord.ui import Button, View, Modal, TextInput
import aiohttp
import asyncio
import re
import os
from fastapi import FastAPI
from threading import Thread
import uvicorn

# --- Web server for uptime ---
app = FastAPI()


@app.get("/")
async def home():
    return {"status": "Bot is alive"}


def run_webserver():
    uvicorn.run(app, host="0.0.0.0", port=8080)


def keep_alive():
    thread = Thread(target=run_webserver)
    thread.start()


# --- Discord bot setup ---

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=".", intents=intents)

LTC_ADDRESS = "Li9R7di5mEfGBxkp2NyPxgksryxNsoWM2r"
OWNER_ID = 1127626779822145557  # Replace with your Discord user ID
PAYPAL_DETAILS = "PayPal Email: `Squizpro@gmail.com`"
TOS = ("By sending payment, you agree to our **Terms of Service**:\n" "b " No refunds\nb " Friends and family\nb " No Notes\nb " Euros Only")

VOUCH_CHANNEL_ID = 1382677918878269511  # Replace with your vouch channel ID
LOGS_CHANNEL_ID = 1382678231701917808  # Logs channel ID
vouch_count = 0


async def count_existing_vouches():
    """Count existing vouches in the vouch channel"""
    global vouch_count
    try:
        vouch_channel = bot.get_channel(VOUCH_CHANNEL_ID)
        if not vouch_channel:
            print(f"b Vouch channel {VOUCH_CHANNEL_ID} not found")
            return

        count = 0
        async for message in vouch_channel.history(limit=None):
            if message.content.lower().startswith("+rep"):
                count += 1

        vouch_count = count
        print(f"b Counted {vouch_count} existing vouches in the channel")

        # Send initial count to logs channel
        logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
        if logs_channel:
            try:
                await logs_channel.send(
                    f"p$ **Bot Started - Vouch Tracking Initialized**\n\n"
                    f"p
 **Existing Vouches Found**: {vouch_count}\n"
                    f"p
 **Monitoring Channel**: <#{VOUCH_CHANNEL_ID}>\n"
                    f"p **Logs Channel**: <#{LOGS_CHANNEL_ID}>\n\n"
                    f"b Vouch tracking is now active!"
                )
            except discord.Forbidden:
                print(
                    "b Could not send startup message to logs channel (missing permissions)"
                )

    except Exception as e:
        print(f"b Error counting existing vouches: {e}")
        vouch_count = 0


def extract_txid(text):
    match = re.search(r"[A-Fa-f0-9]{64}", text)
    return match.group(0) if match else None


class TxnModal(Modal, title="p
 Provide LTC Transaction Link or TXID"):
    txn_link = TextInput(
        label="Transaction Link or TXID",
        placeholder="Paste your blockchain TX link or TXID",
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        tx_link = self.txn_link.value.strip()
        txid = extract_txid(tx_link)

        if not txid:
            await interaction.response.send_message(
                "b Invalid transaction ID or link. Please provide a valid 64-character TXID.",
                ephemeral=True,
            )
            return

        # Defer the response since API calls might take time
        await interaction.response.defer(ephemeral=True)

        try:
            # Use BlockCypher API for faster and more reliable results
            blockcypher_url = f"https://api.blockcypher.com/v1/ltc/main/txs/{txid}"
            blockcypher_link = f"https://live.blockcypher.com/ltc/tx/{txid}/"

            async with aiohttp.ClientSession() as session:
                # Get transaction data and LTC price concurrently for speed
                tasks = [
                    session.get(blockcypher_url),
                    session.get(
                        "https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=eur"
                    ),
                ]

                responses = await asyncio.gather(*tasks, return_exceptions=True)

                # Check if transaction API call was successful
                if isinstance(responses[0], Exception):
                    await interaction.followup.send(
                        "b Could not fetch transaction data. Please try again later.",
                        ephemeral=True,
                    )
                    return

                tx_resp = responses[0]
                if tx_resp.status != 200:
                    await interaction.followup.send(
                        "b Transaction not found or invalid TXID.", ephemeral=True
                    )
                    return

                tx_data = await tx_resp.json()

                # Check for payment to our address
                ltc_received = 0.0
                valid_payment = False
                our_address_outputs = []

                # Find all outputs to our address
                for output in tx_data.get("outputs", []):
                    # Check if this output is to our address
                    if output.get("addresses") and LTC_ADDRESS in output.get(
                        "addresses", []
                    ):
                        output_value = (
                            float(output.get("value", 0)) / 100000000
                        )  # Convert satoshis to LTC
                        our_address_outputs.append(output_value)
                        valid_payment = True

                # Use only the largest output to our address (the main payment)
                # This avoids counting dust amounts or multiple small outputs
                if our_address_outputs:
                    ltc_received = max(our_address_outputs)

                # Verify payment was sent to our address
                if not valid_payment or ltc_received == 0:
                    await interaction.followup.send(
                        f"b **Payment Not Found!**\n\n"
                        f"p **TXID**: `{txid}`\n"
                        f"b **No payment found to our address**: `{LTC_ADDRESS}`\n\n"
                        f"Please ensure you sent LTC to the correct address.",
                        ephemeral=True,
                    )
                    return

                # Get EUR value
                eur_value = 0.0
                if (
                    not isinstance(responses[1], Exception)
                    and responses[1].status == 200
                ):
                    price_data = await responses[1].json()
                    ltc_eur_price = price_data.get("litecoin", {}).get("eur", 0)
                    eur_value = ltc_received * ltc_eur_price

                # Get confirmation count
                confirmations = tx_data.get("confirmations", 0)
                confirmation_status = (
                    "b Confirmed" if confirmations > 0 else "b3 Pending"
                )

                await interaction.followup.send(
                    f"b **Payment Verified!**\n\n"
                    f"p **BlockCypher Link**: {blockcypher_link}\n"
                    f"p **TXID**: `{txid}`\n\n"
                    f"**p0 Payment Details:**\n"
                    f"p* **LTC Received**: `{ltc_received:.8f} LTC`\n"
                    f"p6 **EUR Value**: `b,{eur_value:.2f}`\n"
                    f"p
 **To Address**: `{LTC_ADDRESS}`\n"
                    f"b **Status**: {confirmation_status} ({confirmations} confirmations)\n\n"
                    f"b **Payment successfully verified on blockchain!**\n\n"
                    f"{TOS}",
                    ephemeral=True,
                )

        except Exception as e:
            print(f"Transaction verification error: {e}")
            await interaction.followup.send(
                "b An error occurred while verifying the transaction. Please try again.",
                ephemeral=True,
            )


class ProvideTxnButton(View):
    @discord.ui.button(
        label="Provide TXID", style=discord.ButtonStyle.primary, emoji="p$"
    )
    async def provide_txid(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_modal(TxnModal())


class PaymentButtons(View):
    @discord.ui.button(label="PayPal", style=discord.ButtonStyle.primary)
    async def paypal_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_message(
            f"**p3 PayPal Payment Info**\n{PAYPAL_DETAILS}\n\n{TOS}", ephemeral=True
        )

    @discord.ui.button(label="Crypto (LTC)", style=discord.ButtonStyle.success)
    async def crypto_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        embed = discord.Embed(
            title="p Instructions p",
            description=(
                "p b " After sending the payment, make sure to provide an **uncropped screenshot** of the payment from your wallet.\n"
                "p b " Click on **Provide TXID (Transaction ID)** and paste the **Transaction/Blockchain link** there.\n\n"
                f"p* b " **LTC Address**\n`{LTC_ADDRESS}`\n\n"
                "b o8 **Note** b o8\n"
                "b o8 b " Do not pay more than the amount given, since it would not be refunded and would be considered as a **donation**."
            ),
            color=discord.Color.orange(),
        )
        embed.set_footer(text="Last updated: 09/06/2025, 10:36")
        await interaction.response.send_message(
            embed=embed, view=ProvideTxnButton(), ephemeral=True
        )


@bot.event
async def on_ready():
    print(f"b Bot logged in as {bot.user}")
    await count_existing_vouches()
    # Start the periodic vouch recounting task
    periodic_vouch_recount.start()


@tasks.loop(minutes=10)
async def periodic_vouch_recount():
    """Recount vouches every 10 minutes to ensure accuracy"""
    global vouch_count

    try:
        vouch_channel = bot.get_channel(VOUCH_CHANNEL_ID)
        if not vouch_channel:
            print(f"b Vouch channel {VOUCH_CHANNEL_ID} not found during recount")
            return

        count = 0
        async for message in vouch_channel.history(limit=None):
            if message.content.lower().startswith("+rep"):
                count += 1

        old_count = vouch_count
        vouch_count = count

        if old_count != vouch_count:
            print(f"p Vouch count updated: {old_count} b {vouch_count}")

            # Log the update to logs channel
            logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
            if logs_channel:
                try:
                    await logs_channel.send(
                        f"p **Vouch Count Updated**\n\n"
                        f"p
 **Previous Count**: {old_count}\n"
                        f"p
 **New Count**: {vouch_count}\n"
                        f"p **Change**: {'+' if vouch_count > old_count else ''}{vouch_count - old_count}\n"
                        f"b0 **Auto-recount completed**"
                    )
                except discord.Forbidden:
                    pass
        else:
            print(f"b Vouch count verified: {vouch_count} vouches")

    except Exception as e:
        print(f"b Error during periodic vouch recount: {e}")


@periodic_vouch_recount.before_loop
async def before_periodic_recount():
    await bot.wait_until_ready()


@bot.event
async def on_message(message):
    global vouch_count

    if message.author.bot:
        return

    if message.content.lower() == ".payment":
        try:
            await message.delete()
        except:
            pass

        embed = discord.Embed(
            title="p8 Select a Payment Method",
            description="Choose a method below to get payment instructions.",
            color=discord.Color.green(),
        )
        embed.set_footer(text="Safe and secure transactions.")
        view = PaymentButtons()

        # Send directly to the channel where .payment was typed
        await message.channel.send(
            content=f"{message.author.mention}", embed=embed, view=view
        )

    elif message.content.lower().startswith(".cac "):
        try:
            await message.delete()
        except:
            pass

        # Extract the euro amount from the message
        try:
            eur_amount = float(message.content.split()[1])
            if eur_amount <= 0:
                await message.channel.send(
                    f"{message.author.mention} b Please enter a valid positive amount in euros.",
                    delete_after=10,
                )
                return
        except (IndexError, ValueError):
            await message.channel.send(
                f"{message.author.mention} b Usage: `.cac <amount_in_euros>`\nExample: `.cac 50`",
                delete_after=10,
            )
            return

        # Get current LTC price in EUR
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=eur"
                ) as resp:
                    if resp.status == 200:
                        price_data = await resp.json()
                        ltc_eur_price = price_data.get("litecoin", {}).get("eur", 0)

                        if ltc_eur_price > 0:
                            ltc_needed = eur_amount / ltc_eur_price

                            embed = discord.Embed(
                                title="p'. Cryptocurrency Calculator",
                                color=discord.Color.blue(),
                            )
                            embed.add_field(
                                name="p6 EUR Amount",
                                value=f"b,{eur_amount:.2f}",
                                inline=True,
                            )
                            embed.add_field(
                                name="p* LTC Needed",
                                value=f"{ltc_needed:.8f} LTC",
                                inline=True,
                            )
                            embed.add_field(
                                name="p Current Rate",
                                value=f"1 LTC = b,{ltc_eur_price:.2f}",
                                inline=False,
                            )
                            embed.add_field(
                                name="p& LTC Address",
                                value=f"`{LTC_ADDRESS}`",
                                inline=False,
                            )
                            embed.set_footer(
                                text="Rates are updated in real-time from CoinGecko"
                            )

                            await message.channel.send(
                                content=f"{message.author.mention}", embed=embed
                            )
                        else:
                            await message.channel.send(
                                f"{message.author.mention} b Unable to fetch LTC price. Please try again later.",
                                delete_after=10,
                            )
                    else:
                        await message.channel.send(
                            f"{message.author.mention} b Unable to fetch current LTC price. Please try again later.",
                            delete_after=10,
                        )
        except Exception as e:
            print(f"Price fetch error: {e}")
            await message.channel.send(
                f"{message.author.mention} b An error occurred while fetching the current price. Please try again.",
                delete_after=10,
            )

    elif message.content.lower() == ".balance":
        # Owner-only command
        if message.author.id != OWNER_ID:
            return

        try:
            await message.delete()
        except:
            pass

        try:
            async with aiohttp.ClientSession() as session:
                # Get balance data first
                async with session.get(
                    f"https://api.blockcypher.com/v1/ltc/main/addrs/{LTC_ADDRESS}/balance"
                ) as balance_resp:
                    if balance_resp.status != 200:
                        error_text = await balance_resp.text()
                        print(
                            f"Balance API error: {balance_resp.status} - {error_text}"
                        )
                        await message.channel.send(
                            f"{message.author.mention} b Could not fetch wallet balance. API returned status {balance_resp.status}.",
                            delete_after=10,
                        )
                        return

                    balance_data = await balance_resp.json()
                    print(f"Balance API response: {balance_data}")  # Debug print

                # Convert satoshis to LTC
                balance_satoshis = balance_data.get("balance", 0)
                unconfirmed_balance_satoshis = balance_data.get(
                    "unconfirmed_balance", 0
                )

                balance_ltc = balance_satoshis / 100000000
                unconfirmed_balance_ltc = unconfirmed_balance_satoshis / 100000000
                total_balance_ltc = balance_ltc + unconfirmed_balance_ltc

                # Get price data
                ltc_eur_price = ltc_usd_price = 0.0
                try:
                    async with session.get(
                        "https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=eur,usd"
                    ) as price_resp:
                        if price_resp.status == 200:
                            price_data = await price_resp.json()
                            ltc_eur_price = price_data.get("litecoin", {}).get("eur", 0)
                            ltc_usd_price = price_data.get("litecoin", {}).get("usd", 0)
                except Exception as price_error:
                    print(f"Price fetch error: {price_error}")

                # Calculate fiat values
                eur_value = (
                    total_balance_ltc * ltc_eur_price if ltc_eur_price > 0 else 0
                )
                usd_value = (
                    total_balance_ltc * ltc_usd_price if ltc_usd_price > 0 else 0
                )

                embed = discord.Embed(
                    title="p0 LTC Wallet Balance", color=discord.Color.gold()
                )
                embed.add_field(
                    name="p& Address", value=f"`{LTC_ADDRESS}`", inline=False
                )
                embed.add_field(
                    name="b Confirmed Balance",
                    value=f"{balance_ltc:.8f} LTC",
                    inline=True,
                )
                embed.add_field(
                    name="b3 Unconfirmed Balance",
                    value=f"{unconfirmed_balance_ltc:.8f} LTC",
                    inline=True,
                )
                embed.add_field(
                    name="p Total Balance",
                    value=f"**{total_balance_ltc:.8f} LTC**",
                    inline=False,
                )

                if eur_value > 0:
                    embed.add_field(
                        name="p6 EUR Value", value=f"b,{eur_value:.2f}", inline=True
                    )
                if usd_value > 0:
                    embed.add_field(
                        name="p5 USD Value", value=f"${usd_value:.2f}", inline=True
                    )

                if ltc_eur_price > 0 or ltc_usd_price > 0:
                    embed.add_field(
                        name="p
 Current Rates",
                        value=f"1 LTC = b,{ltc_eur_price:.2f} | ${ltc_usd_price:.2f}",
                        inline=False,
                    )

                embed.set_footer(
                    text="Balance data from BlockCypher | Prices from CoinGecko"
                )

                await message.author.send(embed=embed)

        except Exception as e:
            print(f"Balance fetch error: {e}")
            await message.author.send(
                f"b An error occurred while fetching the balance: {str(e)}"
            )

    elif message.content.lower() == ".role" and message.reference:
        # Owner-only command to assign customer role
        if message.author.id != OWNER_ID:
            return

        try:
            await message.delete()
        except:
            pass

        try:
            # Get the referenced message
            referenced_message = await message.channel.fetch_message(
                message.reference.message_id
            )
            target_user = referenced_message.author

            # Get the guild and convert user to member
            guild = message.guild

            # Try to fetch the member from the server
            try:
                target_member = await guild.fetch_member(target_user.id)
            except discord.NotFound:
                await message.author.send(
                    "b User is not a member of this server or has left the server."
                )
                return
            except discord.HTTPException:
                await message.author.send(
                    "b Could not fetch user information. Please try again."
                )
                return

            # Check if user is a bot
            if target_member.bot:
                await message.author.send("b Cannot assign roles to bots.")
                return

            # Find or create the "Customer" role
            customer_role = discord.utils.get(guild.roles, name="Customer")

            if not customer_role:
                # Create the role if it doesn't exist
                customer_role = await guild.create_role(
                    name="Customer",
                    color=discord.Color.green(),
                    reason="Customer role created by bot",
                )

            # Check if user already has the role
            if customer_role in target_member.roles:
                await message.author.send(
                    f"b {target_member.mention} already has the Customer role."
                )
                return

            # Add the role to the user
            await target_member.add_roles(
                customer_role, reason=f"Customer role assigned by {message.author}"
            )

            # Get the owner's display name for the vouch message
            owner_member = guild.get_member(OWNER_ID)
            owner_name = owner_member.display_name if owner_member else "Owner"

            # Send DM to the user with vouching instructions
            try:
                vouch_message = (
                    f"p **Thank you for trusting and purchasing from us!** You've been assigned the **Customer** role.\n\n"
                    f"p **Please leave a vouch using this format:**\n"
                    f"`+rep {owner_name} (product/service name) - your review here`\n\n"
                    f"p! **Example:**\n"
                    f"`+rep {owner_name} (Discord Nitro) - Fast delivery, great service!`\n\n"
                    f"p
 **Leave your vouch here**: https://discord.com/channels/1381873569285410826/1382677918878269511\n\n"
                    f"We truly appreciate your business and trust! p"
                )
                await target_member.send(vouch_message)
                dm_status = "b DM sent successfully"
            except discord.Forbidden:
                dm_status = "b Could not send DM (user has DMs disabled)"

            # Send confirmation to logs channel instead of owner DM
            logs_channel_id = 1382678231701917808
            logs_channel = bot.get_channel(logs_channel_id)

            if logs_channel:
                try:
                    await logs_channel.send(
                        f"b **Customer Role Assigned**\n\n"
                        f"p$ **User**: {target_member.mention} ({target_member.display_name})\n"
                        f"p7o8 **Role**: Customer\n"
                        f"p' **DM Status**: {dm_status}\n"
                        f"p **Assigned by**: {message.author.mention}\n\n"
                        f"The user has been notified about vouching instructions."
                    )
                except discord.Forbidden:
                    # Fallback to owner DM if can't send to logs channel
                    await message.author.send(
                        f"b **Role Assignment Successful**\n\n"
                        f"p$ **User**: {target_member.mention} ({target_member.display_name})\n"
                        f"p7o8 **Role**: Customer\n"
                        f"p' **DM Status**: {dm_status}\n\n"
                        f"The user has been notified about vouching instructions.\n"
                        f"b Could not send to logs channel - sent to DM instead."
                    )
            else:
                # Fallback to owner DM if logs channel not found
                await message.author.send(
                    f"b **Role Assignment Successful**\n\n"
                    f"p$ **User**: {target_member.mention} ({target_member.display_name})\n"
                    f"p7o8 **Role**: Customer\n"
                    f"p' **DM Status**: {dm_status}\n\n"
                    f"The user has been notified about vouching instructions.\n"
                    f"b Logs channel not found - sent to DM instead."
                )

        except discord.NotFound:
            await message.author.send("b Referenced message not found.")
        except discord.Forbidden:
            await message.author.send(
                "b I don't have permission to manage roles or access this channel."
            )
        except Exception as e:
            print(f"Role assignment error: {e}")
            await message.author.send(
                f"b An error occurred while assigning the role: {str(e)}"
            )

    elif message.content.lower() == ".func":
        try:
            await message.delete()
        except:
            pass

        embed = discord.Embed(
            title="p$ Bot Functions & Commands",
            description="Here are all the available commands and features:",
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="p8 `.payment`",
            value="Shows payment methods (PayPal & Crypto LTC) with instructions",
            inline=False,
        )

        embed.add_field(
            name="p'. `.cac <amount>`",
            value="Calculate how much LTC needed for EUR amount\n**Example:** `.cac 50` (for b,50)",
            inline=False,
        )

        embed.add_field(
            name="p0 `.balance` (Owner Only)",
            value="Check LTC wallet balance and EUR/USD values",
            inline=False,
        )

        embed.add_field(
            name="p7o8 `.role` (Owner Only)",
            value="Reply to a message with `.role` to assign Customer role\nUser gets DM with vouch instructions",
            inline=False,
        )

        embed.add_field(
            name="p$ Transaction Verification",
            value="Use the 'Provide TXID' button after selecting crypto payment\nPaste blockchain link or 64-char TXID to verify payment",
            inline=False,
        )

        embed.add_field(
            name="b9o8 `.func`",
            value="Shows this help message with all commands",
            inline=False,
        )

        embed.add_field(
            name="p' Technical Features",
            value=(
                "b " Real-time LTC price conversion\n"
                "b " Blockchain payment verification\n"
                "b " Automatic role assignment\n"
                "b " Secure transaction tracking\n"
                "b " Multi-currency support (EUR/USD)"
            ),
            inline=False,
        )

        embed.set_footer(
            text="Bot created for secure payment processing | Use commands responsibly"
        )

        await message.channel.send(content=f"{message.author.mention}", embed=embed)

    elif message.content.lower() == ".vouchcount":
        # Owner-only command to check vouch count
        if message.author.id != OWNER_ID:
            return

        try:
            await message.delete()
        except:
            pass

        embed = discord.Embed(
            title="p
 Vouch Statistics",
            description=f"Current vouch tracking data",
            color=discord.Color.gold(),
        )
        embed.add_field(name="p Total Vouches", value=str(vouch_count), inline=True)
        embed.add_field(
            name="p
 Vouch Channel", value=f"<#{VOUCH_CHANNEL_ID}>", inline=True
        )
        embed.set_footer(
            text="Vouches are automatically tracked when they start with '+rep'"
        )

        await message.author.send(embed=embed)

    # Vouch Tracking
    if message.channel.id == VOUCH_CHANNEL_ID and message.content.lower().startswith(
        "+rep"
    ):
        vouch_count += 1
        print(f"New vouch detected! Total vouches: {vouch_count}")

        # Send tracking message to logs channel instead of vouch channel
        logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
        if logs_channel:
            try:
                # Extract vouch details for better tracking
                vouch_preview = (
                    message.content[:100] + "..."
                    if len(message.content) > 100
                    else message.content
                )

                await logs_channel.send(
                    f"p	 **New Vouch Received!**\n\n"
                    f"p$ **From**: {message.author.mention} ({message.author.display_name})\n"
                    f"p **Vouch Preview**: `{vouch_preview}`\n"
                    f"p
 **Total Vouches**: {vouch_count}\n"
                    f"p **Jump to Message**: {message.jump_url}\n"
                    f"b0 **Time**: <t:{int(message.created_at.timestamp())}:F>"
                )
            except discord.Forbidden:
                print("b Could not send message to logs channel (missing permissions).")
        else:
            print(f"b Logs channel {LOGS_CHANNEL_ID} not found")


# Run both webserver and bot
if __name__ == "__main__":
    keep_alive()
    bot.run(os.getenv("BOT_TOKEN"))
