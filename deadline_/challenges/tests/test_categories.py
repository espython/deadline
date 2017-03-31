from django.test import TestCase
from rest_framework.renderers import JSONRenderer

from challenges.models import Challenge, MainCategory, ChallengeDescription, SubCategory, User
from challenges.serializers import MainCategorySerializer, SubCategorySerializer


class CategoryModelTest(TestCase):
    def setUp(self):
        self.c1 = MainCategory(name='Test')
        self.sub1 = SubCategory(name='Unit', meta_category=self.c1)
        self.sub2 = SubCategory(name='Mock', meta_category=self.c1)
        self.sub3 = SubCategory(name='Patch', meta_category=self.c1)
        self.sub1.save();self.sub2.save();self.sub3.save()

    def test_relationships(self):
        """ The categories should be connected"""
        self.assertIn(self.sub1, self.c1.sub_categories.all())
        self.assertEqual(self.sub1.meta_category, self.c1)

    def test_serialize(self):
        """ the Category should show all its subcategories """
        expected_json = '{"name":"Test","sub_categories":["Unit","Mock","Patch"]}'
        received_data = JSONRenderer().render(MainCategorySerializer(self.c1).data)

        self.assertEqual(received_data.decode('utf-8'), expected_json)


class CategoryViewTest(TestCase):
    def setUp(self):
        self.c1 = MainCategory(name='Test')
        self.c2 = MainCategory(name='Data')
        self.c3 = MainCategory(name='Structures')
        self.c4 = MainCategory(name='Rustlang')
        self.c5 = MainCategory(name='Others')
        self.c1.save();self.c2.save();self.c3.save();self.c4.save();self.c5.save()

    def test_view_all_should_return_all_categories(self):
        response = self.client.get('/challenges/categories/all')
        self.assertEqual(response.data, MainCategorySerializer([self.c1, self.c2, self.c3, self.c4, self.c5],
                                                               many=True).data)


class SubCategoryModelTest(TestCase):
    def setUp(self):
        self.sample_desc = ChallengeDescription(content='What Up', input_format='Something',
                                                output_format='something', constraints='some',
                                                sample_input='input sample', sample_output='output sample',
                                                explanation='gotta push it to the limit')
        self.sample_desc.save()
        self.c1 = MainCategory(name='Test')
        self.sub1 = SubCategory(name='Unit', meta_category=self.c1)
        self.sub2 = SubCategory(name='Mock', meta_category=self.c1)
        self.sub3 = SubCategory(name='Patch', meta_category=self.c1)
        self.sub1.save(); self.sub2.save(); self.sub3.save()

    def test_serialize(self):
        """ Ths Subcategory should show all its challenges"""
        c = Challenge(name='TestThis', rating=5, score=10, description=self.sample_desc,
                      test_case_count=5, category=self.sub1)
        c.save()
        expected_json = '{"name":"Unit","challenges":[{"id":1,"name":"TestThis","rating":5,"score":10,"category":"Unit"}]}'
        received_data = JSONRenderer().render(SubCategorySerializer(self.sub1).data)
        self.assertEqual(received_data.decode('utf-8'), expected_json)


class SubCategoryViewTest(TestCase):
    def setUp(self):
        self.sample_desc = ChallengeDescription(content='What Up', input_format='Something',
                                                output_format='something', constraints='some',
                                                sample_input='input sample', sample_output='output sample',
                                                explanation='gotta push it to the limit')
        self.sample_desc.save()
        auth_user = User(username='123', password='123', email='123@abv.bg', score=123)
        auth_user.save()
        self.auth_token = 'Token {}'.format(auth_user.auth_token.key)
        self.c1 = MainCategory(name='Test')
        self.sub1 = SubCategory(name='Unit Tests', meta_category=self.c1)
        self.sub1.save()
        c = Challenge(name='TestThis', rating=5, score=10, description=self.sample_desc, test_case_count=5, category=self.sub1)
        c.save()

    def test_view_subcategory_detail_should_show(self):
        response = self.client.get('/challenges/subcategories/{}'.format(self.sub1.name),
                                   HTTP_AUTHORIZATION=self.auth_token)

        self.assertEqual(response.status_code, 200)
        # Should get the information about a specific subcategory
        self.assertEqual(response.data, SubCategorySerializer(self.sub1).data)

    def test_view_unauthorized_should_401(self):
        response = self.client.get('/challenges/subcategories/{}'.format(self.sub1.name))
        self.assertEqual(response.status_code, 401)

    def test_view_invalid_challenge_should_404(self):
        response = self.client.get('/challenges/subcategories/{}'.format('" OR 1=1;'),
                                   HTTP_AUTHORIZATION=self.auth_token)
        self.assertEqual(response.status_code, 404)