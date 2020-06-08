import random
import string
import requests
from datetime import timedelta, datetime
import urllib2

from app import app, db, search
from app.utils.storage import Storage
from app.models import User, Variable, BitcoinAddress, Transaction, Order, Feedback, Category, Product, Dispute, FavoriteSearch, \
    ProductOffer


def add_fake_products():
    import json

    categories_ids = [category.id for category in Category.query_active().all()]
    if not categories_ids:
        print "No categories to add product to"
        return

    fixtures = json.load(open('tests/fixtures/products.json', 'r'))
    storage = Storage()

    for i, data in enumerate(fixtures):
        product = Product(unique_id=Product.get_unique_id(),
                       category_id=random.choice(categories_ids),
                       seller_id=data['seller_id'],
                       title=data['title'],
                       description=data['description'],
                       price=data['price'],
                       delivery_time=timedelta(days=1),
                       is_approved=True,
                       published_on=datetime.utcnow())

        db.session.add(product)
        db.session.flush()

        search.product_created.send(product=product)

        photo_file = urllib2.urlopen(data['photo']).fp
        photo_aws_key, photo_cloudinary_key = storage.upload_product_photo(photo_file, product.id, product.get_title_seofied(), filename='fake.jpg')
        product_photos = list((dict(aws_key=photo_aws_key, cloudinary_key=photo_cloudinary_key),))
        product.set_data('photos', product_photos)

        print "{0} of {1} is done".format(i + 1, len(fixtures))
    
    db.session.commit()
    print "Added {0} products".format(len(fixtures))


def add_fake_reviews(start, end):


    products = Product.query_active().all()
    storage = Storage()
    count = 0
    feedbacks = ['very professional and on time delivery definitely recommended',
                'thank you very much it was great experience and sure we will deal again',
                'Very patient with my revisions, easy to communicate with and great artwork in the end . thanks',
                'Great work done quickly and exceeded expectation. Bravo!',
                'The best !!!! Great job and quick !!! Thanks a lot !!!',
                'Absolutely awesome. Quick delivery and really happy with the service.',
                'Got exactly what was proposed by the seller. Very satisfied.',
                'Wow, that was fast and easy! The quotes are amazing! Thank you so much',
                'Great work, afforfable price, friendly service!',
                'GREAT!!!! 5 STARS',
                'Excellent quotes and professional work, thank you!',
                'Fabulous experience. Highly Recommend!',
                'Outstanding Experience!',
                'I loved it. thank you!',
                'AMAZING & SUPER FAST WORK!!!! Love it!!!!',
                'Perfect! Thanks',
                'AMAZING RESULTS HIGHLY RECOMMENDED',
                'Great job!',
                'Very prompt and quality work',
                'great job thanks so much brilliant will use you again for sure thank you',
                'Perfect for my needs. Fast delivery. Will hire again.',
                'Fantastic and over delivered, will use again!',
                'Great as always! A++',
                'great seller',
                'Phenomenal and quick!',
                'Great service',
                'Excellent Job. Fast and accurate. Highly recommend.',
                'Super fast delivery and would recommend seller thank you.',
                'Fast response and delivery. I recommend!',
                'Amazing',
                'highly highly reccomend.',
                'Excellent work. Very fast',
                'DEFINITELY GREAT service!!! I HIGHLY recommend him and will use him in the future.',
                'quickly delivered the product. I have received more than I expected',
                'Super!! And fast!!',
                'You are the BEST! Thank you so much for the quick delivery!',
                'Great seller. Went above and beyond what I wanted. Get this service',
                'Wow excellent job. Highly recommended. I will again order in future',
                'Fulfilled order very fast and provided very good work.',
                'Great Experience',
                'Great work excellent response',
                'Total job was performed quickly and very easy thank you very much',
                'By far the best guy in this joint',
                'Thank you very much. I appreciate how prompt you were.Will definitely use again',
                'Super. Well done.',
                'Wonderful experience. Would highly recommend.',
                'Such a quick delivery!!! Thanks, will be back for more later!',
                'Seller was responsive and delivered quality work, will be ordering again.',
                'Delivered on time and easy communication',
                'Great experience! Very helpful and awesome quotes! Thank you!',
                'Excellent',
                'Great Communication, just what i was looking for',
                'very good service.',
                'Super fast and great quality. Thanks!',
                'Many thanks for the extra quotes. 5 stars.',
                'Absolutely outstanding!',
                'Highly recommend! Delivery was fast and professional!'
                'Good Experience!',
                'You are awesome! Appreciate the bonuses, too.',
                'very good seller',
                'Very good job at top speed. would recommend.',
                "It's awesome, Thanks for your efforts."
                'Great work and very fast response rate. Thanks',
                'Great fast service as per service description',
                'Did everything i asked for in super quick time too outstanding experience. I will use again',
                'Awesome experience. overdelivered. highly recommend. will use again.',
                'Excellent service. Cant wait to do business again',
                'Excellent Work. Highly recommended. Very very professional.',
                'Great experience. suprised!',
                'These were terrific!',
                "Awesome seller. I'm very impressed by the speed and quality of his work.",
                'Fast great work. Thank you!',
                'Super quick and easy to deal with. Thanks for your help!',
                'Very well done, I am impressed!',
                'Awesome! Thank you so much!',
                'Excellent service. Will use again!',
                'Thank you! So fast and great!',
                'Great experience with amazing response time!'
                'WOW!! Incredible - AWESOME!! Absolutely order more and again!!',
                'Always a great choice! Good quality and good communication!',
                'Awesome will buy again',
                'Awesome, just what I needed!',
                'Super fast delivery! Excellent customer service!',
                'High quality and fast delivery. Highly recommended contact.',
                'Fantastic Work. Ready to order more',
                'awesome service',
                'Oh my, quick turn around, great work & service!',
                'good will buy again',
                'I love Your Work!!',
                "Awesome what he's doing! Will buy again!",
                'Seller created a great product, on time, and exceeded expectations. Highly recommended!',
                'Provided all as expected and more.',
                'The goal was to purchase he offers, but seller ended up delivering beyond my expectation. Well done!',
                '5* friendly quick service',
                'Brilliant service. will be back soon !',
                'Fast! And he even gave me extra quotes. I recommend him!',
                'Outstanding service. Outstanding Work. Professional and delivered ahead of schedule. Highly recommended',
                'As promised, great product.',
                'More than delivered what was promised! Thanks!',
                'Amazing and timely work! Thank You!!!'
                'great for price.',
                'awesome stuff. replies so fast',
                'Went above and beyond to try and make me happy. Excellent quality of work.',
                'Awesome Content quick turn around',
                'PERFECT! I will order again.',
                'Exactly what I asked for and in very fast time! Highly recommended.',
                'Awesome...over delivered. Great value for money.',
                'An exceptional job! Very fast and above the top.',
                'Great communication, service and options! Appreciate the extra effort and thanks!!!!',
                'Really impressed - seller went above and beyond to make me happy and delivered perfect results in such a quick turnaround.',
                'Really satisfied, thank you!',
                'Excellent customer service and skills from this seller. Highly recommend as always!',
                'Service excellent customer service and skills from this seller. Highly recommend as always!',
                'He is very professional and efficient! I will continue to work with him.',
                'Thank you for your excellent and quick service. I recommend it 100%.',
                'Awesome every time!',
                'always a pleasure!',
                'Perfect',
                'Great speed and service',
                'The best on Jobdone',
                'Really great resource.thank you!',
                'Great service provider!',
                'Perfect! He always comes through!',
                'Fast. Precise. Professional and Serious. I will work again.',
                'He is incredibly patient and professional at his work. Would most definitely work with him again',
                'Quick to reply and any modifications done promptly.',
                'Exactly what you want in an expert! Thanks',
                "Super efficient,capable and patient.I'll be back for more jobs for SURE!",
                'Fast and professional in solving the various problems. Thanks,was a pleasure to work with you.',
                'Good work',
                'I am so happy to have found him and will be using his exclusively for now on.',
                'Very good. I was impressed with the availability and professionalism',
                'He did the job right.Recommended',
                'I had a really great and fast experience! Will definitely be back!',
                'I am really happy with the service provided.',
                'Hands down the best seller on Jobdone!!! No Joke, this guy rocks! Thanks you so much',
                'You are so great - thanks so much.',
                'Exceptional work!',
                'Excellent to deal with and very quick and professional. Would not hesitate to recommend him and will definately be using him again.',
                'Outstanding!! Great Customer Service and Very Fast!',
                'Great and Speedy Experence',
                'I look forward to working with him again.Thank you very much for all',
                "He's the BEST! He went beyond my expectations and delivered all requests in a professional and timely manner. Thanks",
                'His quick response time and excellent communication are above and beyond what I had expected.',
                'I will be glad to hire him again. 10/10. Thank you',
                'You are one of the most cooperative seller that i ever had on Jobdone!',
                'Quick response and did an outstanding job.',
                'great honest person, always online, helps more than what he charges, not money hungry.',
                'Quick turn around and did exactly what I requested. The best on jobdone',
                'Exceptional talent, consistently great experience, and happily recommend.']

    nicknames = open('nicks.txt','r').readlines()
    nick_count = 1

    for product in products:
        try:
            count = random.randint(0, 10)
            print "***** Adding %d reviews to product %s" % (count, product.title)

            for _ in range(count):
                try:
                    import urllib3
                    from requests.packages.urllib3.exceptions import InsecureRequestWarning
                    urllib3.disable_warnings()
                    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


                    fake = requests.get('https://randomuser.me/api/?nat=de,dk,es,fi,fr,gb,ir,nl,us').json()

                    ran_year = str(random.choice(list(range(50,99))))
                    nickk = ( nicknames[nick_count] ).strip()
                    nick_count += 1

                    fake_email = nickk + '@jobdone.net'
                    fake_username = nickk
                    fake_password = (fake['results'][0]['login']['salt']).encode('ascii', 'ignore').decode('ascii')
                    fake_picture_url = fake['results'][0]['picture']['medium']
                    fake_country = fake['results'][0]['nat']

                    print fake_email

                    days = (end - start).days
                    date = start + timedelta(days=random.randint(0, days))

                    user = User(username=fake_username, email=fake_email, password=fake_password, country=fake_country, registered_on=date)
                    prof_image = random.choice([True, False])
                    if prof_image:
                        aws_key, cloudinary_key = storage.upload_profile_photo_from_url(fake_picture_url, user.id, user.username)
                        user.set_photo_data(dict(aws_key=aws_key, cloudinary_key=cloudinary_key))

                    db.session.add(user)
                    db.session.commit()

                except Exception, e:
                    print e
                    continue

                try:
                    order = Order.fake_order(product, user, date)
                    feedtext = feedbacks[count % len(feedbacks)]
                    count = count + 1
                    feedback = Feedback(type=Feedback.ON_SELLER, user_id=user.id, rating=Feedback.POSITIVE, text=feedtext, order_id=order.id, created_on=date)
                    db.session.add(feedback)
                    db.session.commit()
                except:pass

        except Exception as error:
            print error
            continue

