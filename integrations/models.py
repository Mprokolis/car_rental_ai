from django.db import models

class IntegrationInbound(models.Model):
    """
    Αποθηκεύουμε ποια "μηνύματα" έχουμε ήδη επεξεργαστεί,
    για να μην τα εισάγουμε διπλά (idempotency).
    """
    message_id = models.CharField(max_length=255, unique=True)
    subject = models.CharField(max_length=500, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(auto_now_add=True)
    raw_snippet = models.TextField(blank=True)

    def __str__(self):
        return self.message_id
