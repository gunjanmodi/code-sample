# Models.py
from django.db import models

class Service(models.Model):
    # title = models.CharField(max_length=150)
    description =  models.TextField(max_length=500)
    company_name=  models.CharField(max_length=30)
    person_name =  models.CharField(max_length=30)
    facebook_page_url = models.URLField(blank = True, null =True)
    twitter_page_url  = models.URLField(blank = True, null =True)
    linkedin_page_url = models.URLField(blank = True, null =True)
    site_web_url = models.URLField(blank = True, null =True)
    address = models.ManyToManyField(PofileAddress,related_name = 'services_address')
    email_address = models.EmailField('email_address', unique = False)    
    image = models.ImageField(upload_to = 'service', blank=True, null =True)  
    logo = models.ImageField(upload_to = 'service', blank=True, null =True)
    slug = models.SlugField(max_length=150, db_index=True)
    created_by = models.ForeignKey(AUTH_USER_MODEL, related_name='services',
                             verbose_name=_("Services"))
    categories = models.ManyToManyField('Category', related_name='services_cat')
    user_service_count = models.IntegerField(default=0)
    created = models.DateTimeField(default=datetime.now, blank=True, null=True)
    rating = models.FloatField(_('Rating'), null=True, editable=False)

    def __str__(self):
        return self.company_name

    def save(self, *args, **kwargs):
        if not self.slug or Service.objects.filter(slug=self.slug).count() >= 2:
            count = 1
            slug = slugify(self.company_name)
            name = self.company_name

            def _get_query(slug):
                if Service.objects.filter(slug=slug).count():
                    return True

            while _get_query(slug):
                slug = slugify(u'{0}-{1}'.format(name, count))
                while len(slug) > Service._meta.get_field('slug').max_length:
                    name = name[:-1]
                    slug = slugify(u'{0}-{1}'.format(name, count))
                count = count + 1
            self.slug = slug
        super(Service, self).save(*args, **kwargs)

    def get_absolute_url(self):
        """
        Return a product's absolute url
        """
        return reverse('service-detail',
                       kwargs={'pk': self.id})

    def update_rating(self):
        """
        Recalculate rating field
        """
        self.rating = self.calculate_rating()
        self.save()
    update_rating.alters_data = True

    def calculate_rating(self):
        """
        Calculate rating value
        """
        result = self.service_reviews.filter(
            status=self.service_reviews.model.APPROVED
        ).aggregate(
            sum=Sum('score'), count=Count('id'))
        reviews_sum = result['sum'] or 0
        reviews_count = result['count'] or 0
        rating = None
        if reviews_count > 0:
            rating = float(reviews_sum) / reviews_count
        return rating


    def has_review_by(self, user):
        if user.is_anonymous():
            return False
        return self.service_reviews.filter(user=user).exists()

    def is_review_permitted(self, user):
        """
        Determines whether a user may add a review on this product.

        Default implementation respects OSCAR_ALLOW_ANON_REVIEWS and only
        allows leaving one review per user and product.

        Override this if you want to alter the default behaviour; e.g. enforce
        that a user purchased the product to be allowed to leave a review.
        """
        if user.is_authenticated() or settings.OSCAR_ALLOW_ANON_REVIEWS:
            return not self.has_review_by(user)
        else:
            return False
    @cached_property
    def num_approved_reviews(self):
        return self.service_reviews.filter(status=self.service_reviews.model.APPROVED).count()