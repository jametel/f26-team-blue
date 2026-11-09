import os
from decimal import Decimal

import stripe
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.db import transaction
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from core.models import Venue

from core.models import Payments, Queue, SongRequest, UserProfile


@login_required(login_url="login")
@require_POST
def create_priority_checkout(request, venue_slug, request_id):
    # Only a registered customer who owns the request can pay.
    song_request = get_object_or_404(
        SongRequest,
        pk=request_id,
        venue_id__slug=venue_slug,
        requested_by=request.user,
        status=SongRequest.APPROVED,
    )

    profile = get_object_or_404(
        UserProfile,
        user=request.user,
    )

    # Priority is available only for songs already in the queue.
    if not Queue.objects.filter(
        venue_id=song_request.venue_id,
        song_request_id=song_request,
    ).exists():
        return JsonResponse(
            {"error": "This song is not in the queue."},
            status=409,
        )

    # Don't start another checkout for an already paid request.
    if Payments.objects.filter(
        song_request_id=song_request,
        status="COMPLETED",
    ).exists():
        return JsonResponse(
            {"error": "This request already has a completed payment."},
            status=409,
        )

    # Use test-mode configuration only during development.
    secret_key = os.environ.get("STRIPE_SECRET_KEY", "")

    try:
        price_cents = int(
            os.environ.get("PRIORITY_BOOST_PRICE_CENTS", "")
        )
    except ValueError:
        price_cents = 0

    if not secret_key.startswith("sk_test_") or price_cents <= 0:
        return JsonResponse(
            {"error": "Test checkout is not configured."},
            status=503,
        )

    payment = Payments.objects.create(
        user_id=profile,
        song_request_id=song_request,
        amount=Decimal(price_cents) / Decimal("100"),
        status="PENDING",
    )

    return_url = request.build_absolute_uri(
        reverse(
            "venue_customer_dashboard",
            kwargs={"venue_slug": venue_slug},
        )
    )

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": price_cents,
                    "product_data": {
                        "name": "RhytmiQ Priority Boost",
                    },
                },
                "quantity": 1,
            }],
            client_reference_id=str(payment.pk),
            success_url=return_url + "?checkout=returned",
            cancel_url=return_url + "?checkout=cancelled",
            metadata={"payment_id": str(payment.pk)},
            api_key=secret_key,
            idempotency_key=f"rhytmiq-payment-{payment.pk}",
        )
    except stripe.StripeError:
        payment.status = "FAILED"
        payment.save(update_fields=["status"])
        return JsonResponse(
            {"error": "Unable to start checkout."},
            status=502,
        )

    payment.stripe_checkout_session_id = session.id
    payment.save(update_fields=["stripe_checkout_session_id"])

    return redirect(session.url)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    # Webhook signing secret for Stripe test mode.
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    if not webhook_secret.startswith("whsec_"):
        return HttpResponse("Webhook not configured.", status=503)

    # Verify that the event was signed by Stripe.
    try:
        event = stripe.Webhook.construct_event(
            request.body,
            request.headers.get("Stripe-Signature"),
            webhook_secret,
        )
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponse("Invalid webhook.", status=400)

    # Process successful Checkout sessions.
    if event["type"] != "checkout.session.completed":
        return HttpResponse(status=200)

    session = event["data"]["object"]

    # Never mark an unpaid or live-mode session as completed.
    if session.get("payment_status") != "paid":
        return HttpResponse(status=200)

    if session.get("livemode") is not False:
        return HttpResponse(status=400)

    payment_id = (session.get("metadata") or {}).get("payment_id")

    if not payment_id:
        return HttpResponse("Missing payment ID.", status=400)

    # Lock the payment record to prevent duplicate processing.
    with transaction.atomic():
        payment = (
            Payments.objects
            .select_for_update()
            .filter(pk=payment_id)
            .first()
        )

        if payment is None:
            return HttpResponse("Payment not found.", status=400)

        # Verify the event matches our original Checkout session.
        if (
            session.get("id") != payment.stripe_checkout_session_id
            or session.get("client_reference_id") != str(payment.pk)
            or session.get("mode") != "payment"
            or session.get("currency") != "usd"
            or session.get("amount_total") != int(payment.amount * 100)
        ):
            return HttpResponse("Payment mismatch.", status=400)

        payment_intent = session.get("payment_intent")

        if not isinstance(payment_intent, str):
            return HttpResponse("Missing payment intent.", status=400)

        # Repeated delivery must not process the payment twice.
        if payment.status == "COMPLETED":
            return HttpResponse(status=200)

        if payment.status != "PENDING":
            return HttpResponse("Unexpected payment status.", status=409)

        payment.status = "COMPLETED"
        payment.stripe_payment_intent_id = payment_intent

        payment.save(update_fields=[
            "status",
            "stripe_payment_intent_id",
        ])

    return HttpResponse(status=200)


@login_required(login_url="login")
def priority_demo(request, venue_slug):
    venue = get_object_or_404(Venue, slug=venue_slug)

    queued_ids = Queue.objects.filter(
        venue_id=venue
    ).values_list("song_request_id", flat=True)

    requests = SongRequest.objects.filter(
        venue_id=venue,
        requested_by=request.user,
        status=SongRequest.APPROVED,
        pk__in=queued_ids,
    ).select_related("song_id")

    return render(request, "core/priority_demo.html", {
        "venue": venue,
        "song_requests": requests,
    })
